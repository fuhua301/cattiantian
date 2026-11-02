"""Bounded asynchronous animated-WebP decoding. The UI never loads a whole clip."""
from collections import OrderedDict,deque
from pathlib import Path
import threading,time
from PySide6.QtCore import QObject,Signal
from PySide6.QtGui import QImage,QImageReader

class FrameStore(QObject):
    changed=Signal(str,int)
    failed=Signal(str)

    def __init__(self,root,manifest,parent=None,max_bytes=80*1024*1024):
        super().__init__(parent)
        self.root=Path(root)
        self.manifest=manifest
        self.max_bytes=max_bytes
        self.bytes=0
        self.images=OrderedDict()
        self.jobs=deque()
        self.pending=set()
        self.readers=OrderedDict()
        self.cv=threading.Condition()
        self.closed=False
        self.stats={'decoded':0,'decode_ms':0.0,'hits':0,'misses':0,'max_bytes':0}
        # A single neutral still is the only synchronous decode at startup.
        reader=QImageReader(str(self.root/manifest['idle_front']['file']))
        image=reader.read().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        if image.isNull():
            raise RuntimeError('正面待机素材读取失败：'+reader.errorString())
        self.fallback=image.copy()
        self._put(('idle_front',0),image)
        self.worker=threading.Thread(target=self._run,name='cat-frames',daemon=True)
        self.worker.start()
        for name in manifest:
            self.ensure(name,0,ahead=0,urgent=False)

    def _put(self,key,image):
        size=image.sizeInBytes()
        with self.cv:
            if key in self.images:
                self.bytes-=self.images.pop(key).sizeInBytes()
            self.images[key]=image
            self.bytes+=size
            while self.bytes>self.max_bytes and len(self.images)>1:
                old_key,old=self.images.popitem(last=False)
                self.bytes-=old.sizeInBytes()
            self.stats['max_bytes']=max(self.stats['max_bytes'],self.bytes)

    def ensure(self,name,index,ahead=10,urgent=True):
        meta=self.manifest[name]
        indices=[index]
        for n in range(1,ahead+1):
            target=index+n
            if meta['loop']:
                target%=meta['count']
            elif target>=meta['count']:
                break
            indices.append(target)
        with self.cv:
            for target in reversed(indices) if urgent else indices:
                key=(name,target)
                if key in self.images or key in self.pending:
                    continue
                self.pending.add(key)
                if urgent:self.jobs.appendleft(key)
                else:self.jobs.append(key)
            self.cv.notify()

    def get(self,name,index):
        key=(name,index)
        with self.cv:
            image=self.images.get(key)
            if image is not None:
                self.images.move_to_end(key)
                self.stats['hits']+=1
            else:
                self.stats['misses']+=1
        self.ensure(name,index)
        return image

    def ready(self,name,index):
        with self.cv:
            result=(name,index) in self.images
        if not result:self.ensure(name,index)
        return result

    def _reader(self,name,index):
        cached=self.readers.pop(name,None)
        if cached is None or cached[1]>index:
            cached=[QImageReader(str(self.root/self.manifest[name]['file'])),0]
        self.readers[name]=cached
        while len(self.readers)>4:self.readers.popitem(last=False)
        return cached

    def _run(self):
        while True:
            with self.cv:
                while not self.jobs and not self.closed:self.cv.wait()
                if self.closed:return
                name,index=self.jobs.popleft()
                key=(name,index)
                if key in self.images:
                    self.pending.discard(key)
                    continue
            try:
                reader=self._reader(name,index)
                while reader[1]<=index:
                    if self.closed:return
                    start=time.perf_counter()
                    image=reader[0].read()
                    if image.isNull():
                        raise RuntimeError(f'{name} 第{reader[1]}帧读取失败：{reader[0].errorString()}')
                    image=image.convertToFormat(QImage.Format_ARGB32_Premultiplied).copy()
                    number=reader[1]
                    reader[1]+=1
                    self._put((name,number),image)
                    self.stats['decoded']+=1
                    self.stats['decode_ms']+=(time.perf_counter()-start)*1000
                    self.changed.emit(name,number)
            except Exception as error:
                self.failed.emit(str(error))
            finally:
                with self.cv:self.pending.discard(key)

    def close(self):
        with self.cv:
            self.closed=True
            self.cv.notify_all()
        if threading.current_thread() is not self.worker:
            self.worker.join(timeout=.5)

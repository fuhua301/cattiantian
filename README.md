# 小猫桌宠 CatDesktopPet

一个运行在 Windows 桌面上的小猫伙伴，支持摸头、喂食、玩耍、自由散步、睡觉和猫叫声。

## 下载使用

打开本仓库的 [Releases](https://github.com/fuhua301/cattiantian/releases/latest) 页面，下载 `CatDesktopPet.exe`，在 64 位 Windows 上双击运行。该程序无需安装 Python。启动后右键猫咪或通知区域的猫咪图标可打开菜单；双击猫咪可触发扑跳。

首次发布的 Windows 程序由本仓库的 GitHub Actions 自动构建并上传到 Releases；如果刚上传完成，请等待 Actions 构建结束。

- 单击或在头部悬停：摸摸猫咪。
- 按住左键拖动：移动猫咪；滚轮：调整大小。
- 右键菜单：喂食、跑动、睡觉、起名字、音量和开机启动。
- 暂时隐藏后，单击通知区域的猫咪图标可再次显示。

名字、声音和大小等设置存储在当前 Windows 用户的 `%APPDATA%\PhotoCatPet` 目录。更换电脑后需重新设置。

## 从源码运行

需要 64 位 Windows 和 Python 3.13：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python desktop_pet.py
```

本仓库包含程序运行所需的动画和猫叫素材，运行时不需要网络。

## 从源码打包

```powershell
.venv\Scripts\python -m PyInstaller --noconfirm CatDesktopPet.spec
```

生成的文件位于 `dist\CatDesktopPet.exe`。也可在 GitHub 的 Actions 页面手动运行 **Build Windows release**。

## 最新修复

- 清理正面摇头时耳朵的插帧叠影。
- 行走改用完整猫身姿态，取消身体和四肢的分层拼接，并更新相关动作接点。
- 洗脸改为同一只前爪连续完成抬起、舔舐、擦脸和放下。

## 说明

本程序使用二维插画动画，支持桌面置顶、托盘菜单和开机启动。请通过菜单中的“退出桌宠”结束程序。

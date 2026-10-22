"""Clipboard of this isolated X11 desktop, never the host computer's clipboard."""
import os
import stat
import subprocess


def paste(data, mime='UTF8_STRING', send_key=True):
    with subprocess.Popen(['xclip','-selection','clipboard','-in','-target',mime], stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
        process.communicate(data, timeout=4)
    if send_key:
        subprocess.run(['xdotool','key','--clearmodifiers','ctrl+v'], check=True, timeout=4,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def paste_text(text):
    paste(text.encode('utf-8'))


def paste_image(name, send_key=True):
    if not isinstance(name,str) or not name or '/' in name or '\\' in name or name in ('.','..'):
        raise ValueError('图片标识不正确。')
    root = os.open('/profile',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in ('transfer','incoming'):
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
            os.close(root);root=child
        file=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=root)
        with os.fdopen(file,'rb') as source:
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>20*1024*1024:
                raise ValueError('图片最多 20 MB。')
            data=source.read(20*1024*1024+1)
        if len(data)>20*1024*1024:
            raise ValueError('图片最多 20 MB。')
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('剪贴板图片需要 PNG 格式；其他图片请通过文件传输。')
        paste(data,'image/png',send_key=send_key)
    finally:
        os.close(root)

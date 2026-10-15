def check_render_size(rect,scale):
    width=rect.width*scale; height=rect.height*scale
    if width<=0 or height<=0 or width>10000 or height>10000 or width*height>12_000_000:
        raise ValueError('PDF 页面或截图尺寸过大，已阻止渲染以保护本机内存')

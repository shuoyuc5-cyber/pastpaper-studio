"""Assemble a prepared set of authorized PDF regions."""
from pathlib import Path
import pymupdf


def assemble(title, items, kind):
    doc=pymupdf.open();page=None;y=0
    font_path=Path('/System/Library/Fonts/PingFang.ttc')
    font_available=font_path.is_file()
    font = 'studio' if font_available else 'china-s' if any(ord(char)>127 for char in title) else 'helv'
    def new_page():
        nonlocal page,y
        page=doc.new_page(width=595,height=842)
        if font_available:page.insert_font(fontname='studio',fontfile=str(font_path))
        page.insert_text((40,31),'PastPaper Studio | Private practice',fontsize=9,color=(.4,.4,.5))
        page.insert_text((40,823),f'{len(doc)}  |  Original sources retained. Not an official Cambridge paper.',fontsize=8,color=(.4,.4,.5))
        y=55
    def text(value,size=11):
        nonlocal y
        if y+size*2>790:new_page()
        page.insert_textbox(pymupdf.Rect(40,y,555,y+size*3),value,fontname=font,fontsize=size)
        y+=size*2.8
    new_page();text(title,17)
    total=sum(item['marks'] or 0 for item in items)
    text(f'{len(items)} questions | {total} marks | {kind.upper()}',10)
    for item in items:
        text(item['heading'])
        for is_ms,path,segments in item['collections']:
            if is_ms:text('Official Mark Scheme (source extract)',10)
            with pymupdf.open(path) as src:
                for segment in segments:
                    clip=pymupdf.Rect(segment['rect'])
                    scale=min(515/clip.width,680/clip.height,1.25)
                    height=clip.height*scale
                    if y+height>790:new_page()
                    target=pymupdf.Rect(40,y,40+clip.width*scale,y+height)
                    page.show_pdf_page(target,src,segment['page']-1,clip=clip)
                    y+=height+10
        if kind=='qp' and item['space']:
            remaining=item['space']
            while remaining>0:
                if y+25>790:new_page()
                page.draw_line((40,y+20),(555,y+20),color=(.85,.85,.9),width=.5)
                y+=25;remaining-=25
    output=doc.tobytes(garbage=4,deflate=True);doc.close();return output

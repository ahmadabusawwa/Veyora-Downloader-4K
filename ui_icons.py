"""Small original line icons, rendered locally for a consistent desktop appearance."""
from PIL import Image,ImageDraw
import customtkinter as ctk
SHAPES={
 'download': [[(12,2),(12,16)],[(6,10),(12,16),(18,10)],[(3,17),(3,22),(21,22),(21,17)]],
 'home':[[(2,11),(12,2),(22,11)],[(5,10),(5,22),(10,22),(10,15),(15,15),(15,22),(20,22),(20,10)]],
 'audio':[[(8,18),(8,5),(21,2),(21,15)],[(8,9),(21,6)]],
 'list':[[(8,5),(22,5)],[(8,12),(22,12)],[(8,19),(22,19)],[(2,5),(4,5)],[(2,12),(4,12)],[(2,19),(4,19)]],
 'translate':[[(3,2),(18,2),(18,21),(3,21),(3,2)],[(7,16),(11,6),(15,16)],[(8,12),(14,12)]],
 'folder':[[(2,6),(10,6),(12,9),(22,9),(22,21),(2,21),(2,6)]],
 'convert':[[(2,7),(20,7),(16,3)],[(22,17),(4,17),(8,21)]],
 'settings':[[(12,2),(15,7),(21,7),(18,12),(21,18),(15,18),(12,23),(9,18),(3,18),(6,12),(3,7),(9,7),(12,2)]],
 'clock':[[(12,5),(12,12),(17,15)]],
 'help':[[(8,7),(9,4),(15,4),(17,7),(16,10),(12,13),(12,15)],[(12,19),(12,20)]],
}
def icon(name,size=24,color='#bad1e5'):
    im=Image.new('RGBA',(96,96));d=ImageDraw.Draw(im)
    for points in SHAPES[name]:d.line([(x*4,y*4) for x,y in points],fill=color,width=7,joint='curve')
    if name in ('clock','settings'):d.ellipse((5*4,5*4,19*4,19*4) if name=='clock' else (9*4,9*4,15*4,15*4),outline=color,width=6)
    if name=='audio':
        for x,y in [(5,19),(18,16)]:d.ellipse((x*4-7,y*4-5,x*4+7,y*4+5),fill=color)
    return ctk.CTkImage(im,size=(size,size))

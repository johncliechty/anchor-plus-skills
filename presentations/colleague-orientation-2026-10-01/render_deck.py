from pathlib import Path
import win32com.client, json
from PIL import Image, ImageOps, ImageDraw
P=Path(__file__).parent
app=win32com.client.DispatchEx('PowerPoint.Application')
pres=None
try:
    pres=app.Presentations.Open(str(P/'Anchor-Orientation-Mockup-v1.pptx'),True,False,False)
    pres.SaveAs(str(P/'Anchor-Orientation-Mockup-v1.pdf'),32)
    out=P/'preview';out.mkdir(exist_ok=True)
    overflow=[]
    for i in range(1,pres.Slides.Count+1):
        slide=pres.Slides(i)
        slide.Export(str(out/f'slide-{i:02d}.png'),'PNG',1600,900)
        for j in range(1,slide.Shapes.Count+1):
            sh=slide.Shapes(j)
            if sh.HasTextFrame and sh.TextFrame.HasText:
                tf=sh.TextFrame2
                if tf.TextRange.BoundHeight > sh.Height + 3:
                    overflow.append({'slide':i,'text':sh.TextFrame.TextRange.Text[:80],'height':sh.Height,'text_height':tf.TextRange.BoundHeight})
    (P/'render-check.json').write_text(json.dumps({'slides':pres.Slides.Count,'overflow_candidates':overflow},indent=2))
finally:
    if pres:pres.Close()
    app.Quit()
thumbs=[]
for p in sorted((P/'preview').glob('slide-*.png')):
    im=Image.open(p).convert('RGB');im.thumbnail((480,270));thumbs.append(im)
sheet=Image.new('RGB',(1500,5*305+20),'#dae0dd');d=ImageDraw.Draw(sheet)
for i,im in enumerate(thumbs):
    x=10+(i%3)*500;y=10+(i//3)*305;sheet.paste(im,(x,y));d.text((x+5,y+277),f'Slide {i+1}',fill='#152d3a')
sheet.save(P/'Slide-overview.png')
print(json.dumps({'rendered':len(thumbs),'overflow_candidates':overflow},indent=2))

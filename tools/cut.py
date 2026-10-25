import numpy as np
from PIL import Image
from scipy import ndimage
NAMES=['idle','walk1','walk2','sit','sleep','fall','drag','laugh']
def cut(src, pet, key):
    im=np.asarray(Image.open(src).convert('RGB')).astype(np.float32)
    H,W,_=im.shape; r,g,b=im[...,0],im[...,1],im[...,2]
    if key=='green':
        k=g-np.maximum(r,b)        # greenness
    else:
        k=np.minimum(r,b)-g        # magentaness
    a=np.clip(1-(k-40)/70,0,1) if key=='green' else np.clip(1-(k-10)/45,0,1)
    # despill
    out=im.copy()
    if key=='green': out[...,1]=np.minimum(g,np.maximum(r,b)+8)
    else:
        out[...,0]=np.minimum(r,g*1.7+12); out[...,2]=np.minimum(b,g*1.15+10)
        a=np.where(a<0.5,a*0.6,a)
    rgba=np.dstack([out,a*255]).clip(0,255).astype(np.uint8)
    cw,ch=W//4,H//2; frames=[]
    for i,n in enumerate(NAMES):
        cx,cy=(i%4)*cw,(i//4)*ch
        cell=rgba[cy:cy+ch,cx:cx+cw].copy()
        m=cell[...,3]>40
        lab,nl=ndimage.label(ndimage.binary_dilation(m,iterations=6))
        sizes=ndimage.sum(m,lab,range(1,nl+1))
        keep=np.isin(lab,[j+1 for j,s in enumerate(sizes) if s>600])
        cell[~keep]=0
        ys,xs=np.where(cell[...,3]>20)
        frames.append((n,cell[ys.min():ys.max()+1,xs.min():xs.max()+1]))
    ih=frames[0][1].shape[0]; s=280/ih
    for n,f in frames:
        img=Image.fromarray(f); img=img.resize((max(1,round(img.width*s)),max(1,round(img.height*s))),Image.LANCZOS)
        img.save(f'app/sprites/{pet}_{n}.png'); print(pet,n,img.size)
cut('dragon_sheet.jpg','dragon','green'); cut('goblin_sheet.jpg','goblin','magenta')

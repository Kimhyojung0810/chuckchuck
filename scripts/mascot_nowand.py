"""
앱 아이콘(assets/chuckchuck-app-icon-512.png)에서 마법봉만 지운 삐약이 그림을 만든다 (2026-10-12).
/hi 첫 연출에서 봉을 SVG 로 따로 그려 늘이고 돌리려고 (intro.html .wand). 원본 아이콘 파일은 건드리지 않는다.

방법: 봉(손 477,341 → 끝 400,92, 굵기 8 · 끝 구슬 반지름 11 · 빛 테 27) 자리를 가리고,
  ① 바탕 노랑은 cv2.inpaint(TELEA)로 채우고 ② 그 위에 봉이 지나던 눈 흰자 · 볼 · 손(겉 · 안)을 타원으로 맞춰(fitEllipse)
  4×4 표본으로 다시 그린 뒤 ③ 가장자리 6px 를 원본과 섞는다 — 그냥 inpaint 만 하면 눈 흰자가 노랑으로 번졌다.

    python3 -m venv /tmp/cvenv && /tmp/cvenv/bin/pip install opencv-python-headless numpy pillow
    /tmp/cvenv/bin/python scripts/mascot_nowand.py

결과: demo/YEHS_demo/assets/chuckchuck-mascot-nowand-256.png (+ 확인용 512 는 /tmp 에)
"""
import cv2, numpy as np
from PIL import Image
from pathlib import Path
ASSETS=Path(__file__).resolve().parent.parent/'demo'/'YEHS_demo'/'assets'
SRC=str(ASSETS/'chuckchuck-app-icon-512.png')
rgba=np.array(Image.open(SRC)); rgb=rgba[:,:,:3].astype(int)
H,W=rgb.shape[:2]
TIP=(400,92); END=(477,341)
wm=np.zeros((H,W),np.uint8)
cv2.circle(wm,TIP,30,255,-1); cv2.line(wm,TIP,END,255,15); cv2.circle(wm,END,8,255,-1)
near=cv2.dilate(wm,np.ones((9,9),np.uint8))>0
def colmask(c,tol=10):
    return (np.abs(rgb-np.array(c)).sum(2)<=tol)
def fit(region, name, local=0):
    m=region.astype(np.uint8)*255
    m[near]=0
    # 가장 큰 덩어리
    n,lab,st,_=cv2.connectedComponentsWithStats(m)
    k=1+np.argmax(st[1:,cv2.CC_STAT_AREA]); comp=(lab==k).astype(np.uint8)*255
    comp=cv2.morphologyEx(comp,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    cs,_=cv2.findContours(comp,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    c=max(cs,key=cv2.contourArea).reshape(-1,2)
    # 마스크 근처 윤곽점은 버린다(마스크 경계가 윤곽에 섞이지 않게)
    big=cv2.dilate(wm,np.ones((15,15),np.uint8))>0
    keep=~big[c[:,1],c[:,0]] & (c[:,0]<505) & (c[:,0]>263)
    if local:
        far=cv2.dilate(wm,np.ones((local,local),np.uint8))>0
        keep&=far[c[:,1],c[:,0]]
    e=cv2.fitEllipse(c[keep].astype(np.float32))
    print(name,e)
    return e
# 각 층 — 영역은 오른쪽 위 1/4 근처만 본다
roi=np.zeros((H,W),bool); roi[40:430,262:512]=True
eye_reg=(colmask((255,255,255),6)|(rgb.sum(2)<250))&roi
eye_reg[:, :262]=False
eye=fit(eye_reg,'eye',local=121)
blush=fit(colmask((253,207,127),8)&roi,'blush')
hand_out=fit((colmask((240,192,48),10)|colmask((246,202,71),10))&roi,'hand_out')
hand_in=fit(colmask((246,202,71),10)&roi,'hand_in')
# 바탕: 눈 · 볼 · 손까지 가리고 노랑만으로 채운다
bgmask=wm.copy()
for e in (eye,blush,hand_out):
    t=np.zeros((H,W),np.uint8); cv2.ellipse(t,e,255,-1); bgmask|=cv2.dilate(t,np.ones((7,7),np.uint8))
bgmask[:, :300]=0
bg=cv2.inpaint(rgba[:,:,:3][:,:,::-1].copy(),bgmask,7,cv2.INPAINT_TELEA)[:,:,::-1].astype(float)
def inside(e,xs,ys):
    (cx,cy),(w,h),ang=e; a=np.deg2rad(ang)
    dx,dy=xs-cx,ys-cy
    u=dx*np.cos(a)+dy*np.sin(a); v=-dx*np.sin(a)+dy*np.cos(a)
    return (u/(w/2))**2+(v/(h/2))**2<=1
layers=[(blush,(253,207,127)),(eye,(255,255,255)),(hand_out,(240,192,48)),(hand_in,(246,202,71))]
out=rgb.astype(float).copy()
FEATHER=6
D=cv2.dilate(wm,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*FEATHER+1,2*FEATHER+1)))
dist=cv2.distanceTransform((wm==0).astype(np.uint8),cv2.DIST_L2,5)
alpha=np.clip(1-dist/FEATHER,0,1)
ys,xs=np.where(D>0)
S=4; offs=(np.arange(S)+.5)/S-.5
acc=np.zeros((len(xs),3))
for ox in offs:
    for oy in offs:
        sx,sy=xs+ox,ys+oy
        col=bg[ys,xs].copy()
        for e,c in layers:
            m=inside(e,sx,sy); col[m]=c
        acc+=col
a=alpha[ys,xs][:,None]
out[ys,xs]=a*(acc/(S*S))+(1-a)*out[ys,xs]
res=np.dstack([np.clip(out,0,255).astype(np.uint8),rgba[:,:,3]])
Image.fromarray(res).save('/tmp/chuckchuck-mascot-nowand-512.png')
Image.fromarray(res).resize((256,256),Image.LANCZOS).save(str(ASSETS/'chuckchuck-mascot-nowand-256.png'),optimize=True)

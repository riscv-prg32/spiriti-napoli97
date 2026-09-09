#!/usr/bin/env python3
"""Generate PRG32 cartridge graphics from the checked-in pixel-art source PNGs.

The runtime assets intentionally use:
- compact 4-bit indexed sprites for all moving artwork.
- 4-bit packed indexed sprites for small repeated props/effects.
- PRG32 8x8 two-colour tiles for scene/map playfields.

The generated assets.h contains no static pointer-bearing descriptors so portable
cartridges do not depend on data relocations. game.c builds descriptors on stack.
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import math
import numpy as np
from PIL import Image, ImageDraw

try:
    from sklearn.cluster import MiniBatchKMeans
except Exception:
    MiniBatchKMeans = None

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets-src"
OUT = ROOT / "assets.h"
PREVIEW = ROOT / "actual-assets-sheet.png"
SCENE_PREVIEW = ROOT / "actual-tile-scenes.png"

# --- RGB565 / C output -----------------------------------------------------
def rgb565(c):
    r,g,b = c
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def c_u8(name, vals, per=16):
    vals=list(vals)
    lines=[]
    for i in range(0,len(vals),per):
        lines.append("    "+",".join(f"0x{int(v)&255:02X}" for v in vals[i:i+per])+",")
    return f"static const uint8_t {name}[{len(vals)}]={{\n"+"\n".join(lines)+"\n};\n"

def c_u16(name, vals, per=12):
    vals=list(vals)
    lines=[]
    for i in range(0,len(vals),per):
        lines.append("    "+",".join(f"0x{int(v)&0xffff:04X}" for v in vals[i:i+per])+",")
    return f"static const uint16_t {name}[{len(vals)}]={{\n"+"\n".join(lines)+"\n};\n"

# --- sprite conversion -----------------------------------------------------
def border_background_mask(im: Image.Image) -> np.ndarray:
    """Flood-fill the dark panel background from all edges.

    This retains dark outline pixels that are enclosed by the sprite while making
    the surrounding design-sheet panel transparent.
    """
    a=np.asarray(im.convert("RGB"),dtype=np.int16)
    h,w,_=a.shape
    corners=np.concatenate([a[0:3,0:3].reshape(-1,3),a[0:3,-3:].reshape(-1,3),
                            a[-3:,0:3].reshape(-1,3),a[-3:,-3:].reshape(-1,3)],axis=0)
    bg=np.median(corners,axis=0)
    dist=np.sqrt(np.sum((a-bg)**2,axis=2))
    candidate=dist < 54
    # dark blue/black panel background; allow connected antialias edge pixels.
    candidate |= ((a[:,:,0] < 28) & (a[:,:,1] < 42) & (a[:,:,2] < 60))
    seen=np.zeros((h,w),dtype=np.uint8)
    stack=[]
    for x in range(w):
        if candidate[0,x]: stack.append((0,x))
        if candidate[h-1,x]: stack.append((h-1,x))
    for y in range(h):
        if candidate[y,0]: stack.append((y,0))
        if candidate[y,w-1]: stack.append((y,w-1))
    while stack:
        y,x=stack.pop()
        if seen[y,x] or not candidate[y,x]: continue
        seen[y,x]=1
        if x: stack.append((y,x-1))
        if x+1<w: stack.append((y,x+1))
        if y: stack.append((y-1,x))
        if y+1<h: stack.append((y+1,x))
    return seen.astype(bool)

def trim_and_fit(im: Image.Image, size: tuple[int,int]) -> Image.Image:
    im=im.convert("RGB")
    mask=border_background_mask(im)
    ys,xs=np.where(~mask)
    if len(xs)==0:
        raise ValueError("empty sprite")
    pad=2
    x0=max(0,int(xs.min())-pad); x1=min(im.width,int(xs.max())+pad+1)
    y0=max(0,int(ys.min())-pad); y1=min(im.height,int(ys.max())+pad+1)
    crop=im.crop((x0,y0,x1,y1))
    cmask=border_background_mask(crop)
    target_w,target_h=size
    scale=min(target_w/crop.width,target_h/crop.height)
    nw=max(1,int(round(crop.width*scale))); nh=max(1,int(round(crop.height*scale)))
    crop=crop.resize((nw,nh),Image.Resampling.NEAREST)
    cmask_im=Image.fromarray((~cmask*255).astype(np.uint8)).resize((nw,nh),Image.Resampling.NEAREST)
    canvas=Image.new("RGBA",size,(0,0,0,0))
    x=(target_w-nw)//2; y=(target_h-nh)//2
    rgba=crop.convert("RGBA"); rgba.putalpha(cmask_im)
    canvas.alpha_composite(rgba,(x,y))
    return canvas

def indexed_palette_rgba(im: Image.Image, colors=256):
    """Return indices, RGB565 palette, transparent index for an RGBA sprite."""
    rgba=np.asarray(im.convert("RGBA"))
    alpha=rgba[:,:,3]
    marker=(255,0,255)
    rgb=rgba[:,:,:3].copy()
    rgb[alpha==0]=marker
    q=Image.fromarray(rgb.astype(np.uint8)).quantize(colors=colors,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
    inds=np.asarray(q,dtype=np.uint8)
    pal=q.getpalette()[:colors*3]
    pal_rgb=[tuple(pal[i:i+3]) for i in range(0,len(pal),3)]
    # The marker occupies most transparent pixels; select palette entry nearest marker.
    ti=min(range(len(pal_rgb)),key=lambda i:sum((pal_rgb[i][j]-marker[j])**2 for j in range(3)))
    inds=inds.copy(); inds[alpha==0]=ti
    pal565=[rgb565(c) for c in pal_rgb]
    while len(pal565)<colors: pal565.append(0)
    return inds,pal565,ti,pal_rgb

def pack_bitplanes(indices: np.ndarray, bits=8):
    h,w=indices.shape
    row_bytes=(w+7)//8
    out=[]
    for plane in range(bits):
        for y in range(h):
            for bx in range(row_bytes):
                b=0
                for k in range(8):
                    x=bx*8+k
                    if x<w and ((int(indices[y,x])>>plane)&1): b |= 1<<(7-k)
                out.append(b)
    return out

def pack4(indices: np.ndarray):
    h,w=indices.shape; out=[]
    for y in range(h):
        for x in range(0,w,2):
            a=int(indices[y,x])&15; b=int(indices[y,x+1])&15 if x+1<w else 0
            out.append((a<<4)|b)
    return out

# --- small deterministic 4-bpp props --------------------------------------
def make_prop(name,w,h,palette,drawfn):
    im=Image.new("P",(w,h),0)
    im.putpalette(sum(([r,g,b] for r,g,b in palette),[]) + [0]*(768-len(palette)*3))
    draw=ImageDraw.Draw(im); drawfn(draw)
    return name,im,np.asarray(im,dtype=np.uint8),[rgb565(c) for c in palette]

def props():
    p=[]
    p.append(make_prop("trap",24,14,[(0,0,0),(58,63,72),(160,166,177),(255,213,48),(235,45,60),(0,215,255),(255,255,255)],lambda d:(
        d.rectangle((3,5,20,11),fill=2),d.rectangle((5,2,18,5),fill=1),d.rectangle((7,1,16,2),fill=3),
        d.rectangle((7,6,16,7),fill=4),d.rectangle((2,11,21,12),fill=1),d.rectangle((5,12,7,13),fill=5),
        d.rectangle((16,12,18,13),fill=5),d.line((4,4,8,8),fill=6,width=1),d.line((14,4,18,8),fill=6,width=1))))
    p.append(make_prop("slime",18,14,[(0,0,0),(0,186,61),(72,255,128),(188,255,99),(255,238,84),(255,255,255)],lambda d:(
        d.ellipse((2,3,15,12),fill=2),d.ellipse((5,0,11,8),fill=3),d.rectangle((4,8,14,12),fill=2),
        d.rectangle((6,5,7,6),fill=5),d.rectangle((11,5,12,6),fill=5),d.arc((7,7,12,10),0,180,fill=1),d.point((2,13),fill=1),d.point((15,13),fill=1))))
    p.append(make_prop("lamp",16,40,[(0,0,0),(39,43,50),(92,68,42),(255,198,54),(255,244,176),(255,255,255)],lambda d:(
        d.rectangle((7,13,9,39),fill=1),d.rectangle((3,38,13,39),fill=1),d.polygon([(4,5),(12,5),(10,14),(6,14)],fill=2),
        d.rectangle((6,6,10,12),fill=3),d.rectangle((7,7,9,10),fill=4),d.rectangle((7,0,9,5),fill=1),d.point((8,8),fill=5))))
    p.append(make_prop("palm",26,48,[(0,0,0),(34,95,47),(65,153,63),(114,194,76),(132,88,43),(194,141,62)],lambda d:(
        d.polygon([(11,14),(15,14),(17,47),(10,47)],fill=4),d.line((13,16,12,46),fill=5,width=1),
        d.polygon([(13,14),(1,5),(9,10)],fill=2),d.polygon([(13,14),(4,0),(11,9)],fill=3),d.polygon([(13,14),(22,2),(16,10)],fill=3),
        d.polygon([(13,14),(25,8),(17,13)],fill=2),d.polygon([(13,14),(2,16),(10,16)],fill=1),d.polygon([(13,14),(24,18),(16,16)],fill=1))))
    return p

# --- playfield tile compression -------------------------------------------
def local_two_color_tiles(im: Image.Image):
    """Return 720 locally-two-colour 8x8 RGB tiles and their bit encodings."""
    im=im.convert("RGB").resize((320,144),Image.Resampling.NEAREST)
    # 24-color source palette retains the strong design-sheet lighting.
    q=im.quantize(colors=24,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE).convert("RGB")
    tiles=[]; defs=[]
    for ty in range(18):
        for tx in range(40):
            arr=np.asarray(q.crop((tx*8,ty*8,tx*8+8,ty*8+8)),dtype=np.uint8)
            cnt=Counter(map(tuple,arr.reshape(-1,3)))
            cols=[c for c,_ in cnt.most_common(2)]
            if len(cols)==1: cols.append(cols[0])
            bg=np.asarray(cols[0],dtype=np.int16); fg=np.asarray(cols[1],dtype=np.int16)
            pix=arr.astype(np.int16)
            d0=np.sum((pix-bg)**2,axis=2); d1=np.sum((pix-fg)**2,axis=2)
            mask=d1<d0
            recon=np.where(mask[:,:,None],fg,bg).astype(np.uint8)
            bits=[]
            for y in range(8):
                b=0
                for x in range(8):
                    if mask[y,x]: b|=1<<(7-x)
                bits.append(b)
            tiles.append(recon.reshape(-1).astype(np.float32))
            defs.append((tuple(bits),tuple(map(int,fg)),tuple(map(int,bg))))
    return np.stack(tiles),defs

def compress_scene(im: Image.Image, max_tiles=176, seed=7):
    vecs,defs=local_two_color_tiles(im)
    n=len(vecs); k=min(max_tiles,n)
    if MiniBatchKMeans is None:
        # deterministic feature bucketing fallback; generated header is checked in,
        # so this path is only for optional regeneration without scikit-learn.
        sig_to_id={}; medoids=[]; labels=[]
        for i,d in enumerate(defs):
            bits,fg,bg=d
            sig=(bits[0]&0xf0,bits[3],bits[7]&0x0f,fg[0]//64,fg[1]//64,fg[2]//64,bg[0]//64,bg[1]//64,bg[2]//64)
            if sig not in sig_to_id and len(medoids)<k:
                sig_to_id[sig]=len(medoids); medoids.append(i)
            labels.append(sig_to_id.get(sig,0))
    else:
        km=MiniBatchKMeans(n_clusters=k,random_state=seed,batch_size=256,n_init=3,max_iter=80,reassignment_ratio=0.01)
        labels=km.fit_predict(vecs)
        centers=km.cluster_centers_
        medoids=[]
        for ci in range(k):
            idx=np.where(labels==ci)[0]
            if len(idx)==0: medoids.append(0); continue
            sub=vecs[idx]; d=np.sum((sub-centers[ci])**2,axis=1)
            medoids.append(int(idx[int(np.argmin(d))]))
        # remap through nearest actual medoid for consistent map rendering
        med=np.stack([vecs[i] for i in medoids])
        # squared distance via ||a||+||b||-2ab
        aa=np.sum(vecs*vecs,axis=1)[:,None]; bb=np.sum(med*med,axis=1)[None,:]
        dd=aa+bb-2.0*(vecs@med.T)
        labels=np.argmin(dd,axis=1).astype(np.uint8)
    tile_defs=[defs[i] for i in medoids]
    return tile_defs,np.asarray(labels,dtype=np.uint8)

def reconstruct_scene(tile_defs,labels):
    out=Image.new("RGB",(320,144))
    for cell,tid in enumerate(labels):
        bits,fg,bg=tile_defs[int(tid)]; tx=(cell%40)*8; ty=(cell//40)*8
        px=out.load()
        for y,b in enumerate(bits):
            for x in range(8): px[tx+x,ty+y]=fg if (b&(1<<(7-x))) else bg
    return out

# --- source definitions ----------------------------------------------------
SPRITES=[
    ("sn_fiat", "fiat.png", (72,36)),
    ("sn_hunter", "hunter.png", (32,48)),
    ("sn_ghost0", "ghost0.png", (40,40)),
    ("sn_ghost1", "ghost1.png", (40,40)),
    ("sn_ghost2", "ghost2.png", (40,40)),
    ("sn_ghost3", "ghost3.png", (40,40)),
    ("sn_ghost4", "ghost4.png", (40,40)),
    ("sn_ghost5", "ghost5.png", (40,40)),
    ("sn_boss", "boss.png", (96,72)),
]
SCENES=[
    ("sn_map_scene","map.png",(0,0,421,353),112),
    ("sn_centro_scene","centro.png",None,96),
    ("sn_mergellina_scene","mergellina.png",None,96),
    ("sn_porto_scene","porto.png",None,96),
    ("sn_catacombe_scene","catacombe.png",None,96),
    ("sn_palazzo_scene","palazzo.png",None,96),
]

# --- generate --------------------------------------------------------------
def main():
    h=["#ifndef SPIRITI_NAPOLI97_ASSETS_H","#define SPIRITI_NAPOLI97_ASSETS_H","#include <stdint.h>",
       "/* Generated assets: sprites use compact 4-bpp data; scenes use PRG32 8x8 tiles. */"]
    sprite_previews=[]
    for symbol,filename,size in SPRITES:
        im=trim_and_fit(Image.open(SRC/filename),size)
        inds,pal,ti,palrgb=indexed_palette_rgba(im,16)
        pixels=pack4(inds)
        h.append(f"#define {symbol.upper()}_W {size[0]}")
        h.append(f"#define {symbol.upper()}_H {size[1]}")
        h.append(f"#define {symbol.upper()}_TRANSPARENT {ti}")
        h.append(c_u16(symbol+"_palette",pal).rstrip())
        h.append(c_u8(symbol+"_pixels",pixels).rstrip())
        sprite_previews.append((symbol,im))

    for name,im,inds,pal in props():
        symbol="sn_"+name
        h.append(f"#define {symbol.upper()}_W {im.width}")
        h.append(f"#define {symbol.upper()}_H {im.height}")
        h.append(c_u16(symbol+"_palette",pal).rstrip())
        h.append(c_u8(symbol+"_pixels",pack4(inds)).rstrip())
        sprite_previews.append((symbol,im.convert("RGBA")))

    scene_previews=[]
    for si,(symbol,filename,crop,k) in enumerate(SCENES):
        im=Image.open(SRC/filename).convert("RGB")
        if crop: im=im.crop(crop)
        defs,labels=compress_scene(im,k,seed=11+si)
        bits=[]; fg=[]; bg=[]
        for b,f,bgc in defs:
            bits.extend(b); fg.append(rgb565(f)); bg.append(rgb565(bgc))
        h.append(f"#define {symbol.upper()}_TILES {len(defs)}")
        h.append(c_u8(symbol+"_bits",bits).rstrip())
        h.append(c_u16(symbol+"_fg",fg).rstrip())
        h.append(c_u16(symbol+"_bg",bg).rstrip())
        h.append(c_u8(symbol+"_map",labels).rstrip())
        scene_previews.append((symbol,reconstruct_scene(defs,labels)))

    h.append("#endif")
    OUT.write_text("\n".join(h)+"\n")

    # actual sprite preview
    sheet=Image.new("RGB",(640,520),(4,10,22)); d=ImageDraw.Draw(sheet)
    d.text((12,8),"SPIRITI! NAPOLI '97 - ACTUAL RUNTIME SPRITES",fill=(255,255,255))
    x=12;y=30; rowh=0
    for name,im in sprite_previews:
        scale=max(1,min(4,150//max(im.width,1),100//max(im.height,1)))
        view=im.resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST)
        if x+view.width>628: x=12;y+=rowh+34;rowh=0
        checker=Image.new("RGB",view.size,(25,30,38)); checker.paste(view,(0,0),view if view.mode=="RGBA" else None)
        sheet.paste(checker,(x,y)); d.text((x,y+view.height+3),name,fill=(180,220,255))
        x+=view.width+20; rowh=max(rowh,view.height)
    sheet.save(PREVIEW)

    # actual tile-engine reconstruction preview
    tw,th=320,144; cols=2; rows=math.ceil(len(scene_previews)/cols)
    ss=Image.new("RGB",(cols*tw,rows*(th+22)),(3,8,18)); dd=ImageDraw.Draw(ss)
    for i,(name,im) in enumerate(scene_previews):
        xx=(i%cols)*tw; yy=(i//cols)*(th+22); ss.paste(im,(xx,yy)); dd.text((xx+4,yy+146),name,fill=(255,255,255))
    ss.save(SCENE_PREVIEW)

    # Store/gameplay preview composed exclusively from generated runtime art.
    # It is a deterministic asset preview, not a claimed QEMU screenshot.
    scene=dict(scene_previews)["sn_centro_scene"].copy()
    shot=Image.new("RGB",(320,200),(4,10,22)); shot.paste(scene,(0,0))
    # Extend the bottom scene strip where the capture ground/overlay normally sits.
    shot.paste(scene.crop((0,128,320,144)).resize((320,24),Image.Resampling.NEAREST),(0,144))
    sp=dict(sprite_previews)
    def paste_rgba(key,xy):
        im=sp[key].convert("RGBA"); shot.paste(im,xy,im)
    paste_rgba("sn_hunter",(18,105)); paste_rgba("sn_ghost0",(188,50)); paste_rgba("sn_trap",(148,150)); paste_rgba("sn_lamp",(2,105))
    d=ImageDraw.Draw(shot)
    # Actual game beam style.
    for i in range(19):
        x=47+(208-47)*i//18; y=126+(70-126)*i//18; wob=((i*7)&3)-1
        d.rectangle((x,y+wob,x+3,y+wob+1),fill=(0,220,255) if i&1 else (255,120,20))
        if i%5==0: d.point((x+1,y+wob-2),fill=(255,255,255))
    d.rectangle((0,0,319,21),fill=(4,10,22)); d.text((8,6),"CENTRO STORICO",fill=(255,220,60))
    d.rectangle((0,168,319,199),fill=(4,10,22)); d.text((7,171),"A RAGGIO  SIN/DES TRAPPOLA",fill=(255,240,205))
    d.text((7,187),"CATTURA 58     CALORE 34",fill=(190,220,230))
    shot.save(ROOT/"screenshot.png")

    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"wrote {PREVIEW}")
    print(f"wrote {SCENE_PREVIEW}")
    print(f"wrote {ROOT/'screenshot.png'}")

if __name__=="__main__":
    main()

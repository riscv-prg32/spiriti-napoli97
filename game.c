#include "prg32.h"
#include "assets.h"

#define C_BLACK 0x0000
#define C_NAVY 0x0010
#define C_BLUE 0x043F
#define C_CYAN 0x07FF
#define C_WHITE 0xFFFF
#define C_CREAM 0xFFB8
#define C_RED 0xF800
#define C_ORANGE 0xFC00
#define C_YELLOW 0xFFE0
#define C_GREEN 0x07E0
#define C_PURPLE 0x781F
#define C_GRAY 0x8410
#define C_DARKGRAY 0x3186
#define C_SEA 0x0254
#define C_ROAD 0x4208

#define MAX_HAUNTS 6
#define SCENE_MAP 0
#define SCENE_CENTRO 1
#define SCENE_MERGELLINA 2
#define SCENE_PORTO 3
#define SCENE_CATACOMBE 4
#define SCENE_PALAZZO 5

#define TILE_ROAD 240
#define TILE_ROAD_DASH 241
#define TILE_CURB 242
#define TILE_COBBLE 243
#define TILE_RAIL 244

/* No static initialized pointers: portable cartridges build descriptors at runtime. */
typedef enum { ST_TITLE=0, ST_MAP, ST_DRIVE, ST_CAPTURE, ST_RESULT, ST_GAMEOVER } sn_state_t;
typedef struct { int x,y; uint8_t danger; uint8_t active; } haunt_t;

static sn_state_t state;
static uint32_t last_input, rng_state, frame_no;
static int cash, city_energy, score, jobs_done;
static int selected_haunt, target_haunt;
static int car_x, road_scroll, drive_distance, slime_x, slime_y, slime_speed;
static int ghost_x, ghost_y, ghost_vx, trap_x, beam_on, capture_meter, proton_heat;
static int result_timer, loaded_scene;
static uint8_t audio_stereo;

static haunt_t haunts[MAX_HAUNTS] = {
    {116, 61, 2, 1}, {215, 76, 2, 1}, {163, 36, 3, 1},
    {235,110, 3, 1}, { 61,120, 4, 1}, {111, 23, 4, 1}
};

static const char *haunt_name(int id){
    if(id==0) return "CENTRO STORICO";
    if(id==1) return "MERGELLINA";
    if(id==2) return "VOMERO";
    if(id==3) return "PORTO";
    if(id==4) return "FUORIGROTTA";
    return "CAPODIMONTE";
}

static uint32_t rnd(void){ rng_state=rng_state*1664525u+1013904223u; return rng_state; }
static int clampi(int v,int lo,int hi){ return v<lo?lo:(v>hi?hi:v); }
static int abs_i(int v){ return v<0?-v:v; }
static void int_text(int v,char *out){
    char t[12]; int n=0,i,j=0; unsigned int u;
    if(v<0){ out[j++]='-'; u=(unsigned int)(-v); } else u=(unsigned int)v;
    if(!u){ out[j++]='0'; out[j]=0; return; }
    while(u && n<11){ t[n++]=(char)('0'+u%10u); u/=10u; }
    for(i=n-1;i>=0;i--) out[j++]=t[i]; out[j]=0;
}
static void draw_center(int y,const char *s,uint16_t fg,uint16_t bg){
    int len=0; while(s[len]) len++; prg32_gfx_text8((320-len*8)/2,y,s,fg,bg);
}

static void sfx_click(void){ prg32_audio_note_on_pan(4,4,76,170,-18); }
static void sfx_drive(void){ prg32_audio_note_on_pan(4,2,43,120,-30); }
static void sfx_slime(void){ prg32_audio_note_on_pan(5,5,38,190,28); }
static void sfx_beam(void){ prg32_audio_note_on_pan(4,3,67,165,beam_on?24:-24); }
static void sfx_catch(void){ prg32_audio_note_on_pan(4,1,79,235,-20); prg32_audio_note_on_pan(5,1,86,220,25); }
static void sfx_fail(void){ prg32_audio_note_on_pan(4,0,35,180,0); }
static void release_sfx(void){ prg32_audio_note_off(4); prg32_audio_note_off(5); }

static void sprite_draw4(const uint8_t *pixels,const uint16_t *palette,int w,int h,int colors,int x,int y){
    prg32_indexed_sprite_t s;
    s.pixels=pixels; s.palette=palette; s.width=(uint16_t)w; s.height=(uint16_t)h;
    s.frame_count=1; s.palette_count=(uint16_t)colors; s.bits_per_pixel=4; s.transparent_index=0;
    prg32_sprite_draw_indexed(x,y,&s,0);
}
static void define_common_tiles(void){
    static const uint8_t solid[8]={0,0,0,0,0,0,0,0};
    static const uint8_t dash[8]={0,0,0,0x7E,0x7E,0,0,0};
    static const uint8_t curb[8]={0xAA,0x55,0xAA,0x55,0xAA,0x55,0xAA,0x55};
    static const uint8_t cobble[8]={0x99,0x66,0x3C,0xC3,0x99,0x66,0x3C,0xC3};
    static const uint8_t rail[8]={0x81,0x81,0xFF,0x81,0x81,0xFF,0x81,0x81};
    prg32_tile_define(TILE_ROAD,solid,C_ROAD,C_ROAD);
    prg32_tile_define(TILE_ROAD_DASH,dash,C_WHITE,C_ROAD);
    prg32_tile_define(TILE_CURB,curb,C_GRAY,C_DARKGRAY);
    prg32_tile_define(TILE_COBBLE,cobble,C_GRAY,C_DARKGRAY);
    prg32_tile_define(TILE_RAIL,rail,C_DARKGRAY,C_SEA);
}

static void install_scene(const uint8_t *bits,const uint16_t *fg,const uint16_t *bg,
                          const uint8_t *map,int tile_count){
    int i,x,y;
    for(i=0;i<tile_count;i++) prg32_tile_define((uint8_t)i,bits+i*8,fg[i],bg[i]);
    define_common_tiles();
    prg32_playfield_clear(0,0);
    prg32_playfield_clear(1,0);
    /* Repeat the 40-column source across the 64-column playfield so camera
       offsets and driving parallax remain seamless without storing a second map. */
    for(y=0;y<18;y++) for(x=0;x<64;x++)
        prg32_playfield_put(0,(uint8_t)x,(uint8_t)y,map[y*40+(x%40)]);
    prg32_playfield_scroll(0,0,0); prg32_playfield_scroll(1,0,0);
}

static void load_scene(int id){
    if(loaded_scene==id) return;
    if(id==SCENE_MAP) install_scene(sn_map_scene_bits,sn_map_scene_fg,sn_map_scene_bg,sn_map_scene_map,SN_MAP_SCENE_TILES);
    else if(id==SCENE_CENTRO) install_scene(sn_centro_scene_bits,sn_centro_scene_fg,sn_centro_scene_bg,sn_centro_scene_map,SN_CENTRO_SCENE_TILES);
    else if(id==SCENE_MERGELLINA) install_scene(sn_mergellina_scene_bits,sn_mergellina_scene_fg,sn_mergellina_scene_bg,sn_mergellina_scene_map,SN_MERGELLINA_SCENE_TILES);
    else if(id==SCENE_PORTO) install_scene(sn_porto_scene_bits,sn_porto_scene_fg,sn_porto_scene_bg,sn_porto_scene_map,SN_PORTO_SCENE_TILES);
    else if(id==SCENE_CATACOMBE) install_scene(sn_catacombe_scene_bits,sn_catacombe_scene_fg,sn_catacombe_scene_bg,sn_catacombe_scene_map,SN_CATACOMBE_SCENE_TILES);
    else install_scene(sn_palazzo_scene_bits,sn_palazzo_scene_fg,sn_palazzo_scene_bg,sn_palazzo_scene_map,SN_PALAZZO_SCENE_TILES);
    loaded_scene=id;
}

static int scene_for_haunt(int id){
    if(id==0) return SCENE_CENTRO;
    if(id==1) return SCENE_MERGELLINA;
    if(id==2) return SCENE_PALAZZO;
    if(id==3) return SCENE_PORTO;
    if(id==4) return SCENE_CENTRO;
    return SCENE_CATACOMBE;
}

static void prepare_drive_tiles(void){
    int x,y;
    prg32_playfield_clear(1,0);
    for(y=15;y<25;y++) for(x=0;x<64;x++) prg32_playfield_put(1,(uint8_t)x,(uint8_t)y,TILE_ROAD);
    for(x=0;x<64;x++){
        prg32_playfield_put(1,(uint8_t)x,15,TILE_CURB);
        prg32_playfield_put(1,(uint8_t)x,24,TILE_CURB);
        if((x&3)<2) prg32_playfield_put(1,(uint8_t)x,20,TILE_ROAD_DASH);
    }
}
static void prepare_capture_tiles(void){
    int x;
    prg32_playfield_clear(1,0);
    for(x=0;x<64;x++){
        prg32_playfield_put(1,(uint8_t)x,17,TILE_CURB);
        prg32_playfield_put(1,(uint8_t)x,18,TILE_COBBLE);
    }
}

static void enter_map(void){ state=ST_MAP; load_scene(SCENE_MAP); }
static void reset_game(void){
    int i; cash=12000; city_energy=24; score=0; jobs_done=0; selected_haunt=0;
    for(i=0;i<MAX_HAUNTS;i++){ haunts[i].active=1; haunts[i].danger=(uint8_t)(2+(i>>1)); }
}
static void begin_drive(void){
    state=ST_DRIVE; car_x=48; road_scroll=0; drive_distance=0; slime_x=300; slime_y=148;
    slime_speed=3+(haunts[target_haunt].danger>>1);
    load_scene(SCENE_MERGELLINA); prepare_drive_tiles(); sfx_drive();
}
static void begin_capture(void){
    state=ST_CAPTURE; ghost_x=(target_haunt==5)?160:180; ghost_y=(target_haunt==5)?36:54;
    ghost_vx=(rnd()&1u)?2:-2; trap_x=148; beam_on=0; capture_meter=0; proton_heat=0;
    load_scene(scene_for_haunt(target_haunt)); prepare_capture_tiles();
}
static void complete_job(int success){
    int reward=600+haunts[target_haunt].danger*260;
    state=ST_RESULT; result_timer=120;
    if(success){ cash+=reward; score+=reward+city_energy*10; jobs_done++; haunts[target_haunt].active=0; city_energy=clampi(city_energy-2,0,99); sfx_catch(); }
    else { cash-=350; city_energy=clampi(city_energy+3,0,99); sfx_fail(); }
}

void spiriti_napoli97_init(void){
    rng_state=prg32_ticks_ms()^0x4E415039u; frame_no=0; last_input=0; loaded_scene=-1; state=ST_TITLE; reset_game();
    prg32_band_set_game_info("SPIRITI! NAPOLI '97 | A ACTION  B BACK  SELECT SCORES");
    audio_stereo=(uint8_t)(prg32_audio_get_mode()==PRG32_AUDIO_MODE_STEREO);
    prg32_audio_play_track(0);
}

static void update_title(uint32_t p){
    if(p&PRG32_BTN_A){ reset_game(); enter_map(); sfx_click(); }
    if(p&PRG32_BTN_SELECT) prg32_scoreboard_show("spiriti-napoli97","NAPOLI NIGHT SHIFT");
}
static void update_map(uint32_t p){
    int step=0,i,tries;
    if(p&PRG32_BTN_LEFT) step=-1; if(p&PRG32_BTN_RIGHT) step=1;
    if(p&PRG32_BTN_UP) step=-1; if(p&PRG32_BTN_DOWN) step=1;
    if(step){
        for(tries=0;tries<MAX_HAUNTS;tries++){
            selected_haunt=(selected_haunt+step+MAX_HAUNTS)%MAX_HAUNTS;
            if(haunts[selected_haunt].active) break;
        }
        sfx_click();
    }
    if((p&PRG32_BTN_A) && haunts[selected_haunt].active && cash>=250){ cash-=250; target_haunt=selected_haunt; begin_drive(); }
    if(p&PRG32_BTN_B){ state=ST_TITLE; sfx_click(); }
    if(p&PRG32_BTN_SELECT) prg32_scoreboard_show("spiriti-napoli97","NAPOLI NIGHT SHIFT");
    for(i=0;i<MAX_HAUNTS;i++) if(haunts[i].active) break;
    if(i==MAX_HAUNTS || cash<250){ prg32_score_submit_current_player("spiriti-napoli97",(uint32_t)score); state=ST_GAMEOVER; }
}
static void update_drive(uint32_t in,uint32_t p){
    if(in&PRG32_BTN_LEFT) car_x-=3; if(in&PRG32_BTN_RIGHT) car_x+=3; car_x=clampi(car_x,10,238);
    road_scroll=(road_scroll+3)%192; drive_distance+=4; slime_x-=slime_speed;
    prg32_playfield_scroll(0,(int16_t)road_scroll,0); prg32_playfield_scroll(1,(int16_t)(road_scroll*2%192),0);
    if(slime_x<-20){ slime_x=330+(int)(rnd()%110u); slime_y=145+(int)(rnd()%36u); }
    if(abs_i((car_x+36)-slime_x)<32 && abs_i(159-slime_y)<18){ city_energy=clampi(city_energy+1,0,99); score=score>=50?score-50:0; slime_x=350; sfx_slime(); }
    if((frame_no%50u)==0) sfx_drive();
    if(drive_distance>900) begin_capture();
    if(p&PRG32_BTN_B) enter_map();
}
static void update_capture(uint32_t in,uint32_t p){
    int limit_l=(target_haunt==5)?100:40, limit_r=(target_haunt==5)?190:260;
    int center=(target_haunt==5)?ghost_x+48:ghost_x+20;
    if(in&PRG32_BTN_LEFT) trap_x-=3; if(in&PRG32_BTN_RIGHT) trap_x+=3; trap_x=clampi(trap_x,18,278);
    ghost_x+=ghost_vx; if(ghost_x<limit_l || ghost_x>limit_r){ ghost_vx=-ghost_vx; ghost_x+=ghost_vx; }
    ghost_y=(target_haunt==5)?34+(int)((rnd()>>29)&7u):45+(int)((rnd()>>28)&15u);
    beam_on=(in&PRG32_BTN_A)?1:0;
    if(beam_on){
        proton_heat+=2; if((frame_no&7u)==0) sfx_beam();
        if(abs_i((trap_x+12)-center)<(target_haunt==5?42:26)) capture_meter+=2+haunts[target_haunt].danger;
        else capture_meter-=1;
    } else { proton_heat-=2; capture_meter-=1; }
    proton_heat=clampi(proton_heat,0,100); capture_meter=clampi(capture_meter,0,100);
    if(proton_heat>=100){ complete_job(0); return; }
    if(capture_meter>=100){ complete_job(1); return; }
    if(p&PRG32_BTN_B) complete_job(0);
}
static void update_result(void){
    if(result_timer>0) result_timer--;
    if(!result_timer){ release_sfx(); enter_map(); }
}
static void update_gameover(uint32_t p){ if(p&PRG32_BTN_A){ reset_game(); enter_map(); } if(p&PRG32_BTN_B) state=ST_TITLE; }

void spiriti_napoli97_update(void){
    uint32_t in=prg32_input_read(),p=in&~last_input; frame_no++;
    if((frame_no&15u)==0) release_sfx();
    if(state==ST_TITLE) update_title(p); else if(state==ST_MAP) update_map(p); else if(state==ST_DRIVE) update_drive(in,p);
    else if(state==ST_CAPTURE) update_capture(in,p); else if(state==ST_RESULT) update_result(); else update_gameover(p);
    last_input=in;
}

static void draw_vesuvius(int y){
    int i; for(i=0;i<130;i+=4){ int h=(i<65?i:130-i)/3; prg32_gfx_rect(95+i,y-h,4,h,C_DARKGRAY); }
    prg32_gfx_rect(0,y,320,2,C_ORANGE);
}
static void draw_logo(void){
    sprite_draw4(sn_ghost0_pixels,sn_ghost0_palette,SN_GHOST0_W,SN_GHOST0_H,16,48,22);
    prg32_gfx_text8(96,28,"SPIRITI!",C_WHITE,C_NAVY); prg32_gfx_text8(96,45,"NAPOLI '97",C_YELLOW,C_NAVY);
    prg32_gfx_rect(42,18,236,2,C_RED); prg32_gfx_rect(42,65,236,2,C_RED);
}
static void draw_title(void){
    int i; prg32_gfx_clear(C_NAVY); draw_vesuvius(100);
    for(i=0;i<36;i++) if((i*17+(int)frame_no)%7==0) prg32_gfx_rect((i*37)%320,8+(i*19)%78,1,1,C_WHITE);
    draw_logo();
    prg32_gfx_text8(28,112,"UNA NOTTE. SEI QUARTIERI. TROPPI FANTASMI.",C_CREAM,C_NAVY);
    prg32_gfx_text8(60,139,"A  INIZIA IL TURNO DI NOTTE",C_CYAN,C_NAVY);
    prg32_gfx_text8(76,154,"SELECT  CLASSIFICA",C_GRAY,C_NAVY);
    prg32_gfx_text8(48,180,audio_stereo?"PRG32 AUDIO PLUS - STEREO":"PRG32 AUDIO - MONO COMPATIBILE",C_GREEN,C_NAVY);
}

static void draw_map(void){
    int i; char n[12]; load_scene(SCENE_MAP); prg32_playfield_scroll(0,0,0); prg32_playfield_draw_dual();
    for(i=0;i<MAX_HAUNTS;i++){
        uint16_t c=!haunts[i].active?C_GRAY:(i==selected_haunt?C_YELLOW:(haunts[i].danger>=4?C_RED:C_PURPLE));
        if(haunts[i].active){
            prg32_gfx_rect(haunts[i].x-4,haunts[i].y-4,9,9,C_NAVY);
            prg32_gfx_rect(haunts[i].x-2,haunts[i].y-2,5,5,c);
            if(i==selected_haunt) prg32_gfx_rect(haunts[i].x-6,haunts[i].y-6,13,2,C_WHITE);
        } else prg32_gfx_rect(haunts[i].x-2,haunts[i].y-2,5,5,C_GREEN);
    }
    prg32_gfx_rect(0,0,320,18,C_NAVY); prg32_gfx_text8(6,5,"CENTRALE SPIRITICA - NAPOLI 1997",C_WHITE,C_NAVY);
    prg32_gfx_rect(0,164,320,36,C_NAVY); prg32_gfx_text8(5,168,haunt_name(selected_haunt),C_YELLOW,C_NAVY);
    prg32_gfx_text8(5,184,"USCITA L.250K",C_CREAM,C_NAVY); int_text(cash,n); prg32_gfx_text8(121,184,"CASSA",C_GRAY,C_NAVY); prg32_gfx_text8(166,184,n,C_WHITE,C_NAVY);
    int_text(city_energy,n); prg32_gfx_text8(226,184,"PK",C_GRAY,C_NAVY); prg32_gfx_text8(246,184,n,C_RED,C_NAVY);
}

static void draw_drive(void){
    char n[12]; load_scene(SCENE_MERGELLINA); prg32_playfield_draw_dual();
    prg32_gfx_rect(0,0,320,22,C_NAVY); prg32_gfx_text8(8,5,"A BORDO DELLA 500 -",C_CREAM,C_NAVY); prg32_gfx_text8(176,5,haunt_name(target_haunt),C_YELLOW,C_NAVY);
    sprite_draw4(sn_fiat_pixels,sn_fiat_palette,SN_FIAT_W,SN_FIAT_H,16,car_x,132);
    sprite_draw4(sn_palm_pixels,sn_palm_palette,SN_PALM_W,SN_PALM_H,6,4,93);
    sprite_draw4(sn_palm_pixels,sn_palm_palette,SN_PALM_W,SN_PALM_H,6,290,93);
    sprite_draw4(sn_slime_pixels,sn_slime_palette,SN_SLIME_W,SN_SLIME_H,6,slime_x,slime_y);
    int_text((900-drive_distance)/9,n); prg32_gfx_text8(244,25,"DIST",C_GRAY,C_NAVY); prg32_gfx_text8(280,25,n,C_WHITE,C_NAVY);
    prg32_gfx_rect(0,184,320,16,C_NAVY); prg32_gfx_text8(44,188,"SIN/DES GUIDA   B ABBANDONA",C_CREAM,C_NAVY);
}

static void draw_beam(int x0,int y0,int x1,int y1){
    int steps=18,i;
    for(i=0;i<=steps;i++){
        int x=x0+(x1-x0)*i/steps; int y=y0+(y1-y0)*i/steps;
        int wob=((int)((frame_no+i*7u)&3u))-1;
        prg32_gfx_rect(x,y+wob,4,2,(i&1)?C_CYAN:C_ORANGE);
        if((i%5)==0) prg32_gfx_rect(x+1,y+wob-2,2,1,C_WHITE);
    }
}
static void draw_capture(void){
    char n[8]; int center=(target_haunt==5)?ghost_x+48:ghost_x+20;
    load_scene(scene_for_haunt(target_haunt));
    /* Different districts use different camera slices of the repeated 64x32 playfield. */
    prg32_playfield_scroll(0,(int16_t)((target_haunt*31)%192),0); prg32_playfield_scroll(1,0,0); prg32_playfield_draw_dual();
    prg32_gfx_rect(0,0,320,22,C_NAVY); prg32_gfx_text8(8,6,haunt_name(target_haunt),C_YELLOW,C_NAVY);
    if(target_haunt==5)
        sprite_draw4(sn_boss_pixels,sn_boss_palette,SN_BOSS_W,SN_BOSS_H,16,ghost_x-18,ghost_y-10);
    else if(target_haunt==0) sprite_draw4(sn_ghost0_pixels,sn_ghost0_palette,SN_GHOST0_W,SN_GHOST0_H,16,ghost_x,ghost_y);
    else if(target_haunt==1) sprite_draw4(sn_ghost1_pixels,sn_ghost1_palette,SN_GHOST1_W,SN_GHOST1_H,16,ghost_x,ghost_y);
    else if(target_haunt==2) sprite_draw4(sn_ghost2_pixels,sn_ghost2_palette,SN_GHOST2_W,SN_GHOST2_H,16,ghost_x,ghost_y);
    else if(target_haunt==3) sprite_draw4(sn_ghost3_pixels,sn_ghost3_palette,SN_GHOST3_W,SN_GHOST3_H,16,ghost_x,ghost_y);
    else sprite_draw4(sn_ghost4_pixels,sn_ghost4_palette,SN_GHOST4_W,SN_GHOST4_H,16,ghost_x,ghost_y);
    sprite_draw4(sn_hunter_pixels,sn_hunter_palette,SN_HUNTER_W,SN_HUNTER_H,16,18,105);
    sprite_draw4(sn_trap_pixels,sn_trap_palette,SN_TRAP_W,SN_TRAP_H,7,trap_x,150);
    sprite_draw4(sn_lamp_pixels,sn_lamp_palette,SN_LAMP_W,SN_LAMP_H,6,2,105);
    sprite_draw4(sn_lamp_pixels,sn_lamp_palette,SN_LAMP_W,SN_LAMP_H,6,302,105);
    if(target_haunt==1 || target_haunt==2) sprite_draw4(sn_palm_pixels,sn_palm_palette,SN_PALM_W,SN_PALM_H,6,280,95);
    if(beam_on) draw_beam(47,126,center,ghost_y+(target_haunt==5?36:20));
    prg32_gfx_rect(0,168,320,32,C_NAVY); prg32_gfx_text8(7,171,"A RAGGIO  SIN/DES TRAPPOLA",C_CREAM,C_NAVY);
    prg32_gfx_text8(7,187,"CATTURA",C_GRAY,C_NAVY); int_text(capture_meter,n); prg32_gfx_text8(71,187,n,C_GREEN,C_NAVY);
    prg32_gfx_text8(139,187,"CALORE",C_GRAY,C_NAVY); int_text(proton_heat,n); prg32_gfx_text8(195,187,n,C_RED,C_NAVY);
    /* Meter bars make beam alignment readable on a 320x200 LCD. */
    prg32_gfx_rect(232,186,80,4,C_DARKGRAY); prg32_gfx_rect(232,186,(80*proton_heat)/100,4,C_RED);
    prg32_gfx_rect(232,192,80,4,C_DARKGRAY); prg32_gfx_rect(232,192,(80*capture_meter)/100,4,C_GREEN);
}

static void draw_result(void){
    char n[16]; prg32_gfx_clear(C_NAVY); draw_logo();
    if(haunts[target_haunt].active==0) draw_center(91,"SPIRITO CATTURATO!",C_GREEN,C_NAVY); else draw_center(91,"FUGA ECTOPLASMICA!",C_RED,C_NAVY);
    if(haunts[target_haunt].active==0) sprite_draw4(sn_trap_pixels,sn_trap_palette,SN_TRAP_W,SN_TRAP_H,7,148,104);
    prg32_gfx_text8(76,127,"PUNTEGGIO",C_GRAY,C_NAVY); int_text(score,n); prg32_gfx_text8(172,127,n,C_WHITE,C_NAVY);
    prg32_gfx_text8(76,144,"CASSA",C_GRAY,C_NAVY); int_text(cash,n); prg32_gfx_text8(172,144,n,C_YELLOW,C_NAVY);
}
static void draw_gameover(void){
    char n[16]; prg32_gfx_clear(C_NAVY); draw_vesuvius(105); draw_center(42,"TURNO COMPLETATO",C_YELLOW,C_NAVY);
    prg32_gfx_text8(86,124,"PUNTEGGIO",C_GRAY,C_NAVY); int_text(score,n); prg32_gfx_text8(182,124,n,C_WHITE,C_NAVY);
    prg32_gfx_text8(78,151,"A NUOVO TURNO   B TITOLO",C_CREAM,C_NAVY);
}

void spiriti_napoli97_draw(void){
    if(state==ST_TITLE) draw_title(); else if(state==ST_MAP) draw_map(); else if(state==ST_DRIVE) draw_drive();
    else if(state==ST_CAPTURE) draw_capture(); else if(state==ST_RESULT) draw_result(); else draw_gameover();
}

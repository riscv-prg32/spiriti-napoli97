/*
 * Spiriti! Napoli '97 - an unofficial paranormal arcade tribute for PRG32.
 *
 * Graphics are palette-indexed. The ESP32-C6 framebuffer stores one byte per
 * pixel and maps every RGB565 sprite colour to a cell of the firmware's 6x6x6
 * cube, so the cartridge writes each of its colours into the palette entry of
 * its cell (program()). The board then shows the authored colours, exactly as
 * QEMU does. Fades, the capture flash and the glowing spirits are built on
 * that; the sky, the beam, the stars, the sea and the map use palette entries
 * the cube never maps to (IX_*), drawn with the indexed primitives and
 * recoloured every frame.
 *
 * Portable cartridges are loaded at different addresses: no pointer tables in
 * static data, strings come from functions, sprite descriptors are filled at
 * run time.
 */
#include "prg32.h"
#include "assets.h"

#define GAME_ID "spiriti-napoli97"
#define TICK_MS 33u
#define PLAY_Y 16
#define PLAY_H 160
#define HUD_Y (PLAY_Y + PLAY_H)

/* Named colours: exact on both display back ends, used for all text. */
#define WHITE 0xFFFF
#define YELLOW 0xFFE0
#define CYAN 0x07FF
#define GREEN 0x07E0
#define RED 0xF800
#define MAGENTA 0xF81F

/* System palette entries the colour cube never maps to: ours to animate. */
#define IX_BLACK 0
#define IX_WHITE 1
#define IX_RED 2
#define IX_GREEN 3
#define IX_YELLOW 5
#define IX_PANEL 8
#define IX_BAR 9
#define IX_BEAM 10              /* 10..12, cycled */
#define IX_STAR 13
#define IX_CONE 14
#define IX_BOLT 15
#define IX_SKY 232              /* 232..239, top to horizon */
#define IX_SEA 240
#define IX_SAND 241             /* 241..243: beach, land, hills */
#define IX_ROAD 244
#define IX_RING 245
#define IX_GLINT 246
#define IX_PK 247

enum { ST_TITLE, ST_MAP, ST_DRIVE, ST_CAPTURE, ST_RESULT, ST_OVER };
enum { END_SAVED, END_BROKE, END_LOST };
enum { TRACK_TITLE, TRACK_MAP, TRACK_DRIVE, TRACK_CAPTURE, TRACK_BOSS, TRACK_CAUGHT, TRACK_ESCAPED, TRACK_DAWN };
/* Voices 0-3 belong to the tracker; these are the game's. */
enum { V_BEAM = 4, V_FX = 5, V_SIREN = 6, V_LOW = 7 };
enum { I_BEAM = 4, I_BLIP = 5, I_SIREN = 6, I_NOISE = 7, I_ZAP = 8, I_ENGINE = 9 };

#define HAUNTS 7                /* six districts and the Vesuvius */
#define BOSS 6
#define COST 250                /* thousands of lire to send the Fiat out */
#define START_CASH 1500
#define PK_PERIOD 100           /* ticks between one point of PK energy and the next */
#define DRIVE_GOAL 2200
#define SCROLL_WRAP 2560
#define MAX_OBJS 4
#define OBJ_SLIME 0
#define OBJ_CUP 1
#define HUNTER_X 22
#define HUNTER_Y (PLAY_Y + PLAY_H - SN_HUNTER_H - 10)
#define TRAP_Y (PLAY_Y + PLAY_H - SN_TRAP_H - 14)
#define SUCK_TICKS 36

typedef struct { int16_t x; uint8_t lane, kind, on; } obj_t;

static uint8_t state, pending, leaving, ending;
static uint8_t fade, flash, palette_dirty, sky_dirty;
static uint8_t scene, dawn, audio_stereo;
static int8_t spirit;                           /* sprite of the spirit on screen, or -1 */
static uint32_t last_input, unread, rng_state, tick_no, last_ms, acc_ms;
static int cash, pk, score, best, jobs_done, pk_clock;
static uint8_t cleared[HAUNTS];
static int selected, target;
/* drive */
static int scroll, speed, distance, car_x, car_y, car_lane, slip, spawn_in, cups, slimed, siren;
static obj_t objs[MAX_OBJS];
/* capture */
static int ghost_x, ghost_y, ghost_dir, ghost_turn, pull, trap_x, beam_on, beam_was, held, meter, heat, vent;
static int patience, boss_hp, suck, bolt, shake, caught, reward;
static int result_timer;
static int music = -1;
static uint8_t sfx_left[4];
/* Working palettes: the authored colours after the current fade and flash. */
static uint16_t w_scene[16], w_far[4], w_props[16], w_hunter[16], w_fiat[16], w_base[16], w_ghost[16], w_logo[2];

static const int8_t wave16[16] = {0, 5, 9, 11, 12, 11, 9, 5, 0, -5, -9, -11, -12, -11, -9, -5};

/* ---- small helpers ------------------------------------------------------ */
static uint32_t rnd(void) { rng_state = rng_state * 1664525u + 1013904223u; return rng_state >> 8; }
static int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
static int absi(int v) { return v < 0 ? -v : v; }
static int text_len(const char *s) { int n = 0; while (s[n]) n++; return n; }

static const char *haunt_name(int id) {
    if (id == 0) return "CENTRO STORICO";
    if (id == 1) return "MERGELLINA";
    if (id == 2) return "VOMERO";
    if (id == 3) return "PORTO";
    if (id == 4) return "FUORIGROTTA";
    if (id == 5) return "CAPODIMONTE";
    return "VESUVIO";
}
static int haunt_danger(int id) { return id == BOSS ? 5 : 1 + id / 2; }
static int haunt_x(int id) { return id == BOSS ? SN_VESUVIO_X : sn_haunt_xy[id * 2]; }
static int haunt_y(int id) { return PLAY_Y + (id == BOSS ? SN_VESUVIO_Y : sn_haunt_xy[id * 2 + 1]); }
static int haunt_open(int id) { return id == BOSS ? jobs_done >= BOSS && !cleared[BOSS] : !cleared[id]; }
/* Which spirit haunts which district: the purple one likes the palazzo, the slimy one the port. */
static int haunt_spirit(int id) { return id == 2 ? 3 : (id == 3 ? 2 : id); }

static const uint8_t *spirit_pixels(int id) {
    if (id == 0) return sn_ghost0_pixels;
    if (id == 1) return sn_ghost1_pixels;
    if (id == 2) return sn_ghost2_pixels;
    if (id == 3) return sn_ghost3_pixels;
    if (id == 4) return sn_ghost4_pixels;
    if (id == 5) return sn_ghost5_pixels;
    return sn_boss_pixels;
}
static const uint16_t *spirit_pal(int id) {
    if (id == 0) return sn_ghost0_pal;
    if (id == 1) return sn_ghost1_pal;
    if (id == 2) return sn_ghost2_pal;
    if (id == 3) return sn_ghost3_pal;
    if (id == 4) return sn_ghost4_pal;
    if (id == 5) return sn_ghost5_pal;
    return sn_boss_pal;
}
static int spirit_w(void) { return spirit == BOSS ? SN_BOSS_W : SN_GHOST0_W; }
static int spirit_h(void) { return spirit == BOSS ? SN_BOSS_H : SN_GHOST0_H; }

/* ---- audio -------------------------------------------------------------- */
static int pan_at(int x) { return clampi((x - 160) * 2 / 5, -64, 63); }
static void play(int track) {
    if (music == track) return;
    music = track;
    prg32_audio_play_track((uint16_t)track);
}
/* Start an effect on one of the game's voices; ticks == 0 holds it until sfx_stop. */
static void sfx(int voice, int instrument, int note, int volume, int x, int ticks) {
    prg32_audio_note_on_pan((uint8_t)voice, (uint8_t)instrument, (uint8_t)note, (uint8_t)volume, (int8_t)pan_at(x));
    sfx_left[voice - 4] = (uint8_t)ticks;
}
static void sfx_stop(int voice) { prg32_audio_note_off((uint8_t)voice); sfx_left[voice - 4] = 0; }
static void sfx_stop_all(void) { int v; for (v = 4; v < 8; v++) sfx_stop(v); }
static void sfx_tick(void) {
    int v;
    for (v = 0; v < 4; v++)
        if (sfx_left[v] && --sfx_left[v] == 0) prg32_audio_note_off((uint8_t)(v + 4));
}

/* ---- palette ------------------------------------------------------------ */
static uint16_t mix(uint16_t a, uint16_t b, int t, int n) {
    int ar = a >> 11, ag = (a >> 5) & 63, ab = a & 31;
    int br = b >> 11, bg = (b >> 5) & 63, bb = b & 31;
    return (uint16_t)(((ar + (br - ar) * t / n) << 11) | ((ag + (bg - ag) * t / n) << 5) | (ab + (bb - ab) * t / n));
}
static uint16_t fx(uint16_t c) {
    if (flash) c = mix(c, WHITE, flash, 8);
    if (fade < 16) c = mix(0, c, fade, 16);
    return c;
}
static int is_named(uint16_t c) {
    return c == 0 || c == WHITE || c == RED || c == GREEN || c == 0x001F || c == YELLOW || c == CYAN || c == MAGENTA;
}
/* Put a colour in the system palette entry the firmware will choose for it. */
static void program(uint16_t c) {
    unsigned r = (unsigned)(c >> 11) * 5u / 31u, g = (unsigned)((c >> 5) & 63) * 5u / 63u, b = (unsigned)(c & 31) * 5u / 31u;
    if (!is_named(c)) prg32_palette_set((uint8_t)(16u + r * 36u + g * 6u + b), c);
}
static void group(uint16_t *work, const uint16_t *authored, int n) {
    int i;
    work[0] = 0;
    for (i = 1; i < n; i++) { work[i] = fx(authored[i]); program(work[i]); }
}
static void sky_apply(void) {
    uint16_t top = dawn ? 0x3A9F : sn_sky_pal[scene * 2], low = dawn ? 0xFD0A : sn_sky_pal[scene * 2 + 1];
    int i;
    /* Psychokinetic energy stains the night sky green as it builds up. */
    for (i = 0; i < 8; i++)
        prg32_palette_set((uint8_t)(IX_SKY + i), fx(mix(mix(top, low, i, 7), 0x3EC7, dawn ? 0 : pk, 220)));
    prg32_palette_set(IX_PK, mix(0xA01F, 0x3FE7, pk, 100));
    sky_dirty = 0;
}
static void palette_apply(void) {
    group(w_scene, sn_scene_pal + scene * 16, 16);
    group(w_far, sn_far_pal + scene * 4, 4);
    group(w_props, sn_props_pal, 16);
    group(w_hunter, sn_hunter_pal, 16);
    group(w_fiat, sn_fiat_pal, 16);
    if (spirit >= 0) group(w_base, spirit_pal(spirit), 16);
    program(SN_UI_NAVY);                        /* text backgrounds stay navy through a fade */
    prg32_palette_set(IX_SEA, fx(0x0A4E));
    prg32_palette_set(IX_SAND, fx(0xDE0F));
    prg32_palette_set(IX_SAND + 1, fx(0x2BC8));
    prg32_palette_set(IX_SAND + 2, fx(0x452A));
    prg32_palette_set(IX_ROAD, fx(0xEF19));
    sky_apply();
    palette_dirty = 0;
}
/* Entries that move every frame: beam, stars, sea glints, the selection ring. */
static void animate(void) {
    static const uint16_t beam[4] = {0xFC60, YELLOW, WHITE, CYAN};
    int i;
    for (i = 0; i < 3; i++) prg32_palette_set((uint8_t)(IX_BEAM + i), fx(beam[(i + (tick_no >> 1)) & 3]));
    prg32_palette_set(IX_STAR, fx((tick_no >> 3) & 1 ? WHITE : 0x7BF4));
    prg32_palette_set(IX_GLINT, fx((tick_no >> 3) & 1 ? 0x5DDF : 0x1B36));
    prg32_palette_set(IX_RING, fx((tick_no >> 2) & 1 ? YELLOW : RED));
    prg32_palette_set(IX_CONE, fx((tick_no & 1) ? WHITE : 0xAFFF));
    prg32_palette_set(IX_BOLT, fx((tick_no & 1) ? WHITE : YELLOW));
    if (sky_dirty) sky_apply();
}
/* The spirit glows by sliding along its own dark-to-bright ramp: every colour
 * it shows is one of its authored colours, so no palette entry changes. */
static void ghost_colours(void) {
    int shift = (int)((tick_no >> 3) & 3), i;
    if (shift == 3) shift = 1;
    if (held && (tick_no & 2)) shift += 3;
    for (i = 1; i < 16; i++) w_ghost[i] = (suck && (tick_no & 2)) ? WHITE : w_base[clampi(i + shift, 1, 15)];
    w_ghost[0] = 0;
}

/* ---- drawing ------------------------------------------------------------ */
static void sprite(const uint8_t *pixels, const uint16_t *pal, int w, int h, int bpp, int frames, int frame, int x, int y) {
    prg32_indexed_sprite_t s;
    s.pixels = pixels; s.palette = pal; s.width = (uint16_t)w; s.height = (uint16_t)h;
    s.frame_count = (uint16_t)frames; s.palette_count = (uint16_t)(1 << bpp); s.bits_per_pixel = (uint8_t)bpp;
    s.transparent_index = 0;
    prg32_sprite_draw_indexed(x, y, &s, (uint32_t)frame);
}
static void box(int x, int y, int w, int h, int index) {
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > 320) w = 320 - x;
    if (y + h > 200) h = 200 - y;
    if (w > 0 && h > 0) prg32_gfx_rect_indexed(x, y, w, h, (uint8_t)index);
}
static void text(int x, int y, const char *s, uint16_t fg) { prg32_gfx_text8(x, y, s, fg, SN_UI_NAVY); }
static void centred(int y, const char *s, uint16_t fg) { text((320 - text_len(s) * 8) / 2, y, s, fg); }
static int number(int x, int y, int v, uint16_t fg) {
    char t[12], out[12];
    int n = 0, j = 0;
    unsigned u = (unsigned)(v < 0 ? -v : v);
    if (v < 0) out[j++] = '-';
    do { t[n++] = (char)('0' + u % 10u); u /= 10u; } while (u && n < 10);
    while (n) out[j++] = t[--n];
    out[j] = 0;
    text(x, y, out, fg);
    return j * 8;
}
static void meter_bar(int x, int y, int w, int value, int top, int index) {
    box(x, y, w, 6, IX_BAR);
    box(x, y, w * clampi(value, 0, top) / top, 6, index);
}
static void sky(void) {
    int i;
    for (i = 0; i < 8; i++) box(0, PLAY_Y + i * 20, 320, 20, IX_SKY + i);
}
static void stars(void) {
    uint32_t h = 0x9E3779B9u;
    int i;
    for (i = 0; i < 28; i++) {
        h = h * 1664525u + 1013904223u;
        box((int)((h >> 8) % 320u), PLAY_Y + (int)((h >> 20) % 70u), 1, 1, (i & 3) ? IX_WHITE : IX_STAR);
    }
}
/* How far a row of the road has scrolled: the bay crawls, the asphalt runs. */
static int row_scroll(int row) {
    if (row < 3) return 0;
    if (row == 3) return scroll >> 3;
    if (row == 4) return scroll >> 2;
    if (row == 5) return scroll >> 1;
    return scroll;
}
static void rows(const uint8_t *map, int first, int last, int road, int dy) {
    prg32_indexed_sprite_t s;
    int row, col, wave = (int)((tick_no >> 4) & 1);
    s.pixels = sn_tiles; s.palette = w_scene; s.width = 16; s.height = 16; s.frame_count = SN_TILE_COUNT;
    s.palette_count = 16; s.bits_per_pixel = 4; s.transparent_index = 0;
    for (row = first; row <= last; row++) {
        int moved = road ? row_scroll(row) : 0, start = moved >> 4, off = moved & 15, n = off ? 21 : 20;
        for (col = 0; col < n; col++) {
            int code = map[row * SN_SCENE_COLS + (start + col) % SN_SCENE_COLS];
            if (!code) continue;
            if (code == SN_T_WATER && wave) code = SN_T_WATER_B;
            prg32_sprite_draw_indexed(col * 16 - off, PLAY_Y + row * 16 + dy, &s, (uint32_t)(code - 1));
        }
    }
}
static void far_vesuvius(int x, int y) { sprite(sn_far_pixels, w_far, SN_FAR_W, SN_FAR_H, 2, 1, 0, x, y); }
static void prop_lamp(int x, int y) { sprite(sn_lamp_pixels, w_props, SN_LAMP_W, SN_LAMP_H, 4, 1, 0, x, y); }
static void top_band(const char *title, uint16_t fg) {
    box(0, 0, 320, PLAY_Y, IX_PANEL);
    text(4, 4, title, fg);
}
static void cash_readout(void) {
    text(216, 4, "CASSA", CYAN);
    text(264 + number(264, 4, cash, WHITE), 4, "K", WHITE);
}
static void bottom_band(void) { box(0, HUD_Y, 320, 200 - HUD_Y, IX_PANEL); }

/* ---- state changes ------------------------------------------------------ */
static void go(int next) {
    if (leaving) return;
    leaving = 1;
    pending = (uint8_t)next;
}
static void new_game(void) {
    int i;
    cash = START_CASH; pk = 20; score = 0; jobs_done = 0; selected = 0; pk_clock = 0; dawn = 0;
    for (i = 0; i < HAUNTS; i++) cleared[i] = 0;
}
static void finish(int how) {
    ending = (uint8_t)how;
    if (how == END_SAVED) score += cash * 2 + (100 - pk) * 20;
    if (score > best) best = score;
    prg32_score_submit_current_player(GAME_ID, (uint32_t)score);
    go(ST_OVER);
}
static void enter(int next) {
    int i;
    state = (uint8_t)next;
    sfx_stop_all();
    spirit = -1;
    held = suck = bolt = shake = 0;
    if (next == ST_TITLE) {
        scene = 1; spirit = 0; dawn = 0; scroll = 0;
        play(TRACK_TITLE);
    } else if (next == ST_MAP) {
        scene = 1;
        if (!haunt_open(selected))
            for (i = 0; i < HAUNTS; i++) if (haunt_open(i)) { selected = i; break; }
        play(TRACK_MAP);
    } else if (next == ST_DRIVE) {
        scene = 1;
        scroll = distance = slip = cups = slimed = 0;
        speed = 4; car_lane = 1; car_x = 30; car_y = PLAY_Y + 124 - SN_FIAT_H + 16; spawn_in = 30; siren = 0;
        for (i = 0; i < MAX_OBJS; i++) objs[i].on = 0;
        play(TRACK_DRIVE);
        sfx(V_LOW, I_ENGINE, 38, 90, car_x, 0);
    } else if (next == ST_CAPTURE) {
        scene = (uint8_t)target; spirit = (int8_t)haunt_spirit(target);
        ghost_x = 200; ghost_dir = (rnd() & 1) ? 1 : -1; ghost_turn = 40; pull = 0; ghost_y = PLAY_Y + 20;
        trap_x = 150; beam_on = beam_was = meter = heat = vent = 0;
        patience = clampi(820 + cups * 150 - slimed * 60 - haunt_danger(target) * 30, 400, 1400);
        boss_hp = target == BOSS ? 3 : 1;
        if (target == BOSS) ghost_x = 112;
        play(target == BOSS ? TRACK_BOSS : TRACK_CAPTURE);
    } else if (next == ST_RESULT) {
        scene = (uint8_t)target;
        result_timer = 110;
        music = -1;
        play(caught ? TRACK_CAUGHT : TRACK_ESCAPED);
    } else {
        scene = 1; dawn = ending == END_SAVED; spirit = (int8_t)(ending == END_SAVED ? -1 : 0);
        music = -1;
        play(ending == END_SAVED ? TRACK_DAWN : TRACK_ESCAPED);
    }
    palette_dirty = 1;
}
static void complete_job(int success) {
    caught = success;
    if (success) {
        reward = 400 + haunt_danger(target) * 200 + patience / 4;
        cash += reward; score += reward + (100 - pk) * 5;
        cleared[target] = 1; jobs_done++;
        pk = clampi(pk - 10, 0, 100);
    } else {
        reward = -150;
        cash += reward;
        pk = clampi(pk + 10, 0, 100);
    }
    go(ST_RESULT);
}

/* ---- simulation, one 33 ms step ---------------------------------------- */
static void show_scores(void) {
    prg32_scoreboard_show(GAME_ID, "TURNO DI NOTTE");
    last_ms = prg32_ticks_ms();
    acc_ms = 0;
}
static void tick_title(uint32_t pressed) {
    scroll = (scroll + 2) % SCROLL_WRAP;
    if (pressed & PRG32_BTN_A) { new_game(); sfx(V_FX, I_BLIP, 84, 170, 160, 4); go(ST_MAP); }
    else if (pressed & PRG32_BTN_SELECT) show_scores();
}
static void tick_map(uint32_t pressed) {
    int step = 0, tries;
    if (pressed & (PRG32_BTN_LEFT | PRG32_BTN_UP)) step = -1;
    if (pressed & (PRG32_BTN_RIGHT | PRG32_BTN_DOWN)) step = 1;
    if (step) {
        for (tries = 0; tries < HAUNTS; tries++) {
            selected = (selected + step + HAUNTS) % HAUNTS;
            if (haunt_open(selected)) break;
        }
        sfx(V_FX, I_BLIP, 76, 150, haunt_x(selected), 3);
    }
    if ((pressed & PRG32_BTN_A) && haunt_open(selected) && cash >= COST) {
        cash -= COST; target = selected;
        sfx(V_FX, I_ZAP, 72, 170, haunt_x(selected), 6);
        go(ST_DRIVE);
    }
    if (pressed & PRG32_BTN_B) go(ST_TITLE);
}
static void tick_drive(uint32_t in, uint32_t pressed) {
    int want = slip ? 1 : ((in & PRG32_BTN_RIGHT) ? 6 : ((in & PRG32_BTN_LEFT) ? 2 : 4));
    int lane_y, i, danger = haunt_danger(target);
    if (pressed & PRG32_BTN_UP) car_lane = clampi(car_lane - 1, 0, 2);
    if (pressed & PRG32_BTN_DOWN) car_lane = clampi(car_lane + 1, 0, 2);
    lane_y = PLAY_Y + 124 - SN_FIAT_H + car_lane * 16;
    car_y += clampi(lane_y - car_y, -3, 3);
    if ((tick_no & 3) == 0 && speed != want) {
        speed += speed < want ? 1 : -1;
        sfx(V_LOW, I_ENGINE, 34 + speed * 2, 90, car_x, 0);
    }
    car_x += clampi(18 + speed * 6 - car_x, -1, 1);
    if (slip) slip--;
    scroll = (scroll + speed) % SCROLL_WRAP;
    distance += speed;
    /* The two-tone siren follows the car across the stereo field. */
    if ((tick_no % 14u) == 0) { siren ^= 1; sfx(V_SIREN, I_SIREN, siren ? 81 : 76, 70, car_x + 36, 12); }
    if (--spawn_in <= 0) {
        spawn_in = 34 - danger * 3 + (int)(rnd() % 26u);
        for (i = 0; i < MAX_OBJS; i++)
            if (!objs[i].on) {
                objs[i].on = 1; objs[i].x = 330; objs[i].lane = (uint8_t)(rnd() % 3u);
                objs[i].kind = (uint8_t)((rnd() % 5u) == 0 ? OBJ_CUP : OBJ_SLIME);
                break;
            }
    }
    for (i = 0; i < MAX_OBJS; i++) {
        if (!objs[i].on) continue;
        objs[i].x = (int16_t)(objs[i].x - speed);
        if (objs[i].x < -30) { objs[i].on = 0; continue; }
        if (objs[i].lane == car_lane && absi(car_y - lane_y) < 8 && objs[i].x < car_x + 62 && objs[i].x + 20 > car_x + 10) {
            objs[i].on = 0;
            if (objs[i].kind == OBJ_CUP) {
                if (cups < 3) cups++;
                score += 50;
                sfx(V_FX, I_BLIP, 88, 170, car_x + 36, 5);
            } else {
                slip = 24; shake = 8; slimed++;
                pk = clampi(pk + 2, 0, 100); sky_dirty = 1;
                sfx(V_FX, I_NOISE, 40, 200, car_x + 36, 8);
            }
        }
    }
    if (distance >= DRIVE_GOAL) go(ST_CAPTURE);
    if (pressed & PRG32_BTN_B) go(ST_MAP);
}
static void tick_capture(uint32_t in, uint32_t pressed) {
    int w = spirit_w(), boss = target == BOSS, danger = haunt_danger(target);
    int lo = boss ? 70 : 64, hi = 312 - w, centre, aligned, pace;
    if (suck) {
        /* The trap has it: the spirit is drawn down behind the ground. */
        ghost_x += clampi(trap_x + SN_TRAP_W / 2 - w / 2 - ghost_x, -6, 6);
        ghost_y += 4;
        if (--suck == 0) complete_job(1);
        return;
    }
    if (in & PRG32_BTN_LEFT) trap_x -= 4;
    if (in & PRG32_BTN_RIGHT) trap_x += 4;
    trap_x = clampi(trap_x, 64, 320 - SN_TRAP_W - 8);
    if (vent && heat <= 40) vent = 0;
    beam_on = (in & PRG32_BTN_A) && !vent;
    centre = ghost_x + w / 2;
    aligned = absi(trap_x + SN_TRAP_W / 2 - centre) < (boss ? 40 : 24);
    held = beam_on;
    /* A held spirit struggles on the spot; a free one roams, faster with danger. */
    pace = held ? ((tick_no & 1) ? 1 : 0) : 1 + (danger + 1) / 2 + (boss && boss_hp < 3 ? 1 : 0);
    ghost_x += ghost_dir * pace;
    if (held) ghost_x += (int)(rnd() % 3u) - 1;
    if (ghost_x < lo) { ghost_x = lo; ghost_dir = 1; }
    if (ghost_x > hi) { ghost_x = hi; ghost_dir = -1; }
    if (--ghost_turn <= 0) { ghost_turn = 30 + (int)(rnd() % 70u); if (rnd() & 1) ghost_dir = -ghost_dir; }
    pull = clampi(pull + (held && aligned ? 1 : -1), 0, boss ? 16 : 44);
    ghost_y = PLAY_Y + (boss ? 6 : 14) + pull + wave16[(tick_no >> 1) & 15] * (boss ? 1 : 2) / 2;
    if (beam_on) {
        heat += 2;
        meter += aligned ? (boss ? 2 : 3) : 0;
        if ((tick_no & 3) == 0) sfx(V_BEAM, I_BEAM, 48 + heat / 6 + (int)(tick_no & 4), 120, centre, 0);
    } else {
        if (beam_was) sfx_stop(V_BEAM);
        heat -= vent ? 3 : 1;
        if ((tick_no & 1) == 0) meter--;
    }
    if (!aligned && (tick_no & 3) == 0) meter--;
    beam_was = beam_on;
    heat = clampi(heat, 0, 100); meter = clampi(meter, 0, 100);
    if (heat >= 100 && !vent) {
        /* The pack overheats: it vents and the beam is off until it cools. */
        vent = 1; shake = 6;
        sfx(V_FX, I_NOISE, 62, 190, HUNTER_X, 10);
    }
    if (boss) {
        /* The crater answers with lightning: firing through it overheats the pack. */
        if (bolt) bolt--;
        else if ((tick_no % 96u) == 95u) {
            bolt = 5; shake = 8; flash = 3; palette_dirty = 1;
            if (beam_on) heat = clampi(heat + 18, 0, 100);
            sfx(V_LOW, I_NOISE, 30, 230, centre, 14);
        }
    }
    if ((tick_no % 120u) == 60u && !held) sfx(V_SIREN, I_SIREN, 62 + (int)(rnd() % 8u), 90, centre, 10);
    if (meter >= 100) {
        meter = 0; flash = 6; palette_dirty = 1;
        sfx(V_FX, I_ZAP, 70 + boss_hp * 4, 220, centre, 12);
        if (--boss_hp > 0) { shake = 10; ghost_dir = -ghost_dir; pull = 0; }
        else { suck = SUCK_TICKS; held = 0; beam_on = beam_was = 0; sfx_stop(V_BEAM); }
        return;
    }
    if (--patience <= 0 || (pressed & PRG32_BTN_B)) complete_job(0);
}
static void tick_result(uint32_t pressed) {
    if (result_timer > 0) result_timer--;
    if (result_timer == 0 || (result_timer < 80 && (pressed & PRG32_BTN_A))) {
        if (cleared[BOSS]) finish(END_SAVED);
        else if (pk >= 100) finish(END_LOST);
        else if (cash < COST) finish(END_BROKE);
        else go(ST_MAP);
    }
}
static void tick_over(uint32_t pressed) {
    scroll = (scroll + 1) % SCROLL_WRAP;
    if (pressed & PRG32_BTN_A) { new_game(); go(ST_MAP); }
    else if (pressed & PRG32_BTN_B) go(ST_TITLE);
    else if (pressed & PRG32_BTN_SELECT) show_scores();
}
static void tick(uint32_t in, uint32_t pressed) {
    tick_no++;
    sfx_tick();
    if (flash) { flash--; palette_dirty = 1; }
    if (shake) shake--;
    if (leaving) {
        if (fade > 0) { fade = (uint8_t)(fade - 4); palette_dirty = 1; }
        if (fade == 0) { leaving = 0; enter(pending); }
        return;
    }
    if (fade < 16) { fade = (uint8_t)(fade + 4); palette_dirty = 1; }
    /* The city's psychokinetic energy climbs while spirits are loose. */
    if (state == ST_MAP || state == ST_DRIVE || state == ST_CAPTURE) {
        if (++pk_clock >= PK_PERIOD) {
            pk_clock = 0; pk = clampi(pk + 1, 0, 100); sky_dirty = 1;
            if (pk >= 100 && !suck) { finish(END_LOST); return; }
        }
    }
    if (state == ST_TITLE) tick_title(pressed);
    else if (state == ST_MAP) tick_map(pressed);
    else if (state == ST_DRIVE) tick_drive(in, pressed);
    else if (state == ST_CAPTURE) tick_capture(in, pressed);
    else if (state == ST_RESULT) tick_result(pressed);
    else tick_over(pressed);
}

/* ---- entry points ------------------------------------------------------- */
void spiriti_napoli97_init(void) {
    static const uint16_t named[8] = {0x0000, 0xFFFF, 0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF, 0xF81F};
    int i;
    /* The firmware keeps the palette between cartridges: restore what the text relies on. */
    for (i = 0; i < 8; i++) prg32_palette_set((uint8_t)i, named[i]);
    prg32_palette_set(IX_PANEL, SN_UI_NAVY);
    prg32_palette_set(IX_BAR, 0x2146);
    last_ms = prg32_ticks_ms();
    rng_state = prg32_random_number(1, 0x7FFFFFFFu) ^ last_ms;
    acc_ms = 0; tick_no = 0; last_input = unread = 0; best = 0;
    leaving = 0; fade = 0; flash = 0; music = -1; ending = END_SAVED;
    for (i = 0; i < 4; i++) sfx_left[i] = 0;
    new_game();
    audio_stereo = (uint8_t)(prg32_audio_get_mode() == PRG32_AUDIO_MODE_STEREO);
    prg32_band_set_game_info("SPIRITI! NAPOLI '97");
    enter(ST_TITLE);
}

void spiriti_napoli97_update(void) {
    uint32_t now = prg32_ticks_ms(), in = prg32_input_read();
    uint32_t elapsed = now - last_ms;
    int steps = 0;
    last_ms = now;
    unread |= in & ~last_input;                 /* a press waits for the next step, it is never lost */
    last_input = in;
    /* Fixed 33 ms steps keep the pace when the board draws slower than 30 fps. */
    acc_ms += elapsed > 4u * TICK_MS ? 4u * TICK_MS : elapsed;
    while (acc_ms >= TICK_MS && steps < 4) {
        acc_ms -= TICK_MS;
        tick(in, unread);
        unread = 0;
        steps++;
    }
}

static void draw_title(void) {
    static const uint16_t cycle[4] = {YELLOW, WHITE, CYAN, WHITE};
    int bob = wave16[(tick_no >> 2) & 15] / 2;
    sky(); stars();
    far_vesuvius(196, PLAY_Y + 41);
    rows(sn_scene_maps + SN_SCENE_COLS * SN_SCENE_ROWS, 0, 9, 0, 0);
    prop_lamp(8, PLAY_Y + 92); prop_lamp(296, PLAY_Y + 92);
    w_logo[0] = 0; w_logo[1] = 0;
    sprite(sn_logo_pixels, w_logo, SN_LOGO_W, SN_LOGO_H, 1, 1, 0, 23, PLAY_Y + 15);
    w_logo[1] = fade == 16 ? cycle[(tick_no >> 3) & 3] : 0;
    sprite(sn_logo_pixels, w_logo, SN_LOGO_W, SN_LOGO_H, 1, 1, 0, 20, PLAY_Y + 12);
    box(60, PLAY_Y + 46, 112, 12, IX_PANEL);
    text(76, PLAY_Y + 48, "NAPOLI '97", YELLOW);
    ghost_colours();
    sprite(spirit_pixels(0), w_ghost, SN_GHOST0_W, SN_GHOST0_H, 4, 1, 0, 252, PLAY_Y + 14 + bob);
    sprite(sn_fiat_pixels, w_fiat, SN_FIAT_W, SN_FIAT_H, 4, 1, 0, (scroll % 420) - 80, PLAY_Y + 116);
    top_band(audio_stereo ? "PRG32 AUDIO PLUS  STEREO" : "PRG32 AUDIO  MONO", GREEN);
    bottom_band();
    centred(HUD_Y + 3, "UNA NOTTE. SEI QUARTIERI. UN VULCANO.", WHITE);
    centred(HUD_Y + 13, (tick_no & 16) ? "A  INIZIA IL TURNO   SELECT  CLASSIFICA" : "                                       ", CYAN);
}

static void draw_map(void) {
    /* Roads between the districts: pairs of marker numbers. */
    static const uint8_t links[14] = {4, 1, 1, 0, 0, 3, 1, 2, 2, 5, 5, 0, 3, 6};
    int layer, row, run, i, n = 0;
    uint32_t h = 0x1234567u;
    box(0, PLAY_Y, 320, PLAY_H, IX_SEA);
    for (i = 0; i < 26; i++) {
        h = h * 1664525u + 1013904223u;
        box((int)(((h >> 8) + (tick_no >> 3)) % 320u), PLAY_Y + 96 + (int)((h >> 20) % 62u), 3, 1, IX_GLINT);
    }
    for (layer = 0; layer < SN_MAP_LAYERS; layer++)
        for (row = 0; row < SN_MAP_ROWS; row++)
            for (run = 0; run < SN_MAP_RUNS; run++, n += 2)
                if (sn_map_runs[n + 1] > sn_map_runs[n])
                    box(sn_map_runs[n] * SN_MAP_CELL, PLAY_Y + row * SN_MAP_CELL,
                        (sn_map_runs[n + 1] - sn_map_runs[n]) * SN_MAP_CELL, SN_MAP_CELL, IX_SAND + layer);
    far_vesuvius(SN_MAP_FAR_X, PLAY_Y + SN_MAP_FAR_Y);
    for (i = 0; i < 14; i += 2) {
        int x0 = haunt_x(links[i]), y0 = haunt_y(links[i]), x1 = haunt_x(links[i + 1]), y1 = haunt_y(links[i + 1]);
        int steps = (absi(x1 - x0) + absi(y1 - y0)) / 7, s;
        for (s = 1; s < steps; s++) box(x0 + (x1 - x0) * s / steps, y0 + (y1 - y0) * s / steps, 2, 2, IX_ROAD);
    }
    for (i = 0; i < HAUNTS; i++) {
        int x = haunt_x(i) - 8, y = haunt_y(i) - 8;
        if (i == BOSS && jobs_done < BOSS) continue;
        if (haunt_open(i)) y += wave16[((tick_no >> 1) + (uint32_t)i * 5u) & 15] / 4;
        if (i == selected && haunt_open(i)) {
            box(x - 3, y - 3, 22, 2, IX_RING); box(x - 3, y + 17, 22, 2, IX_RING);
            box(x - 3, y - 3, 2, 22, IX_RING); box(x + 17, y - 3, 2, 22, IX_RING);
        }
        sprite(sn_mark_pixels, w_props, SN_MARK_W, SN_MARK_H, 4, 2, cleared[i] ? 1 : 0, x, y);
    }
    top_band("CENTRALE SPIRITI", YELLOW);
    cash_readout();
    bottom_band();
    text(4, HUD_Y + 3, haunt_name(selected), YELLOW);
    text(132, HUD_Y + 3, "PERICOLO", CYAN);
    for (i = 0; i < haunt_danger(selected); i++) text(204 + i * 8, HUD_Y + 3, "*", RED);
    text(260, HUD_Y + 3, "PK", CYAN);
    number(280, HUD_Y + 3, pk, pk >= 70 ? RED : WHITE);
    text(4, HUD_Y + 13, "A USCITA 250K", WHITE);
    meter_bar(132, HUD_Y + 14, 180, pk, 100, IX_PK);
}

static void draw_drive(void) {
    int dy = shake ? (int)(tick_no & 2) - 1 : 0, i, pass, x;
    int car_wobble = slip ? wave16[(tick_no * 3u) & 15] / 4 : 0;
    sky(); stars();
    far_vesuvius(196, PLAY_Y + 25);
    rows(sn_road_map, 0, 9, 1, dy);
    for (i = 0; i < 3; i++) {
        x = i * 160 + 40 - scroll % 160;
        sprite(sn_palm_pixels, w_props, SN_PALM_W, SN_PALM_H, 4, 1, 0, x, PLAY_Y + 52 + dy);
        prop_lamp(x + 84, PLAY_Y + 68 + dy);
    }
    /* Painter's order: what is in a lane above the car goes behind it. */
    for (pass = 0; pass < 2; pass++) {
        for (i = 0; i < MAX_OBJS; i++) {
            int oy = PLAY_Y + 124 + objs[i].lane * 16 + dy;
            if (!objs[i].on || (objs[i].lane > car_lane) != pass) continue;
            if (objs[i].kind == OBJ_CUP) sprite(sn_cup_pixels, w_props, SN_CUP_W, SN_CUP_H, 4, 1, 0, objs[i].x, oy - SN_CUP_H - 2);
            else sprite(sn_slime_pixels, w_props, SN_SLIME_W, SN_SLIME_H, 4, 1, 0, objs[i].x, oy - SN_SLIME_H);
        }
        if (!pass) {
            sprite(sn_fiat_pixels, w_fiat, SN_FIAT_W, SN_FIAT_H, 4, 1, 0, car_x, car_y + dy + car_wobble);
            box(car_x + 22, car_y + dy + car_wobble + 2, 6, 2, IX_RING);      /* the roof beacon */
        }
    }
    top_band("IN VIAGGIO", CYAN);
    text(92, 4, haunt_name(target), YELLOW);
    bottom_band();
    text(4, HUD_Y + 3, "STRADA", CYAN);
    meter_bar(60, HUD_Y + 4, 120, distance, DRIVE_GOAL, IX_GREEN);
    text(196, HUD_Y + 3, "CAFFE'", CYAN);
    for (i = 0; i < cups; i++) text(252 + i * 8, HUD_Y + 3, "*", YELLOW);
    text(4, HUD_Y + 13, "SU/GIU CORSIA  SIN/DES GAS  B RIENTRA", WHITE);
}

static void draw_beam(int x0, int y0, int x1, int y1) {
    int i, steps = (absi(x1 - x0) > absi(y1 - y0) ? absi(x1 - x0) : absi(y1 - y0)) / 5 + 1;
    for (i = 0; i <= steps; i++) {
        int x = x0 + (x1 - x0) * i / steps, y = y0 + (y1 - y0) * i / steps;
        int wob = wave16[(i * 3 + (int)tick_no * 2) & 15] * (i < steps - i ? i : steps - i) / 40;
        box(x - 2, y + wob - 1, 6, 3, IX_BEAM + (i + (int)tick_no) % 3);
        box(x - 2, y + wob, 6, 1, IX_WHITE);
    }
    box(x1 - 4, y1 - 1, 8, 3, IX_BEAM); box(x1 - 1, y1 - 4, 3, 8, IX_BEAM + 1);
}
/* The trap's light cone: thin scan lines fanning up from the open doors. */
static void draw_cone(int height) {
    int i, cx = trap_x + SN_TRAP_W / 2;
    for (i = 0; i < height; i += 3) box(cx - 5 - i / 4, TRAP_Y - i, 10 + i / 2, 1, IX_CONE);
}
static void draw_bolt(void) {
    uint32_t h = tick_no / 6u * 2654435761u;
    int x = 60 + (int)((h >> 8) % 200u), y = PLAY_Y, i;
    for (i = 0; i < 7; i++) {
        int nx = x + (int)((h >> (i * 3)) & 15u) - 7;
        box(nx < x ? nx : x, y, absi(nx - x) + 2, 2, IX_BOLT);
        box(nx, y, 2, 12, IX_BOLT);
        x = nx; y += 12;
    }
}
static void draw_capture(void) {
    int dy = shake ? (int)(tick_no & 2) - 1 : 0, w = spirit_w(), h = spirit_h();
    int centre = ghost_x + w / 2, aligned = absi(trap_x + SN_TRAP_W / 2 - centre) < (target == BOSS ? 40 : 24);
    const uint8_t *map = sn_scene_maps + scene * SN_SCENE_COLS * SN_SCENE_ROWS;
    int outdoors = scene != 2 && scene != 5;
    sky();
    if (outdoors) stars();
    if (scene == 1) far_vesuvius(196, PLAY_Y + 41);
    rows(map, 0, 7, 0, dy);
    ghost_colours();
    if (suck) sprite(spirit_pixels(spirit), w_ghost, w, h, 4, 1, 0, ghost_x, ghost_y + dy);
    rows(map, 8, 9, 0, dy);
    if (bolt) draw_bolt();
    if (outdoors && target != BOSS) { prop_lamp(4, PLAY_Y + 92 + dy); prop_lamp(300, PLAY_Y + 92 + dy); }
    if (suck) draw_cone(TRAP_Y - PLAY_Y - 20);
    else if (beam_on && aligned) draw_cone(40 + (int)(tick_no & 7));
    if (!suck) sprite(spirit_pixels(spirit), w_ghost, w, h, 4, 1, 0, ghost_x, ghost_y + dy);
    sprite(sn_trap_pixels, w_props, SN_TRAP_W, SN_TRAP_H, 4, 1, 0, trap_x, TRAP_Y + dy);
    sprite(sn_hunter_pixels, w_hunter, SN_HUNTER_W, SN_HUNTER_H, 4, 1, 0, HUNTER_X, HUNTER_Y + dy);
    if (beam_on) draw_beam(HUNTER_X + 30, HUNTER_Y + 22 + dy, centre, ghost_y + h / 2 + dy);
    top_band(haunt_name(target), YELLOW);
    cash_readout();
    bottom_band();
    text(4, HUD_Y + 3, "CATTURA", CYAN);
    meter_bar(64, HUD_Y + 4, 84, meter, 100, IX_GREEN);
    text(160, HUD_Y + 3, vent ? "SFIATO" : "CALORE", vent ? RED : CYAN);
    meter_bar(212, HUD_Y + 4, 100, heat, 100, heat >= 75 || vent ? IX_RED : IX_YELLOW);
    text(4, HUD_Y + 13, "TEMPO", CYAN);
    meter_bar(64, HUD_Y + 14, 84, patience, 1400, patience < 200 ? IX_RED : IX_WHITE);
    text(160, HUD_Y + 13, "A RAGGIO  SIN/DES", WHITE);
}

static void draw_result(void) {
    box(0, 0, 320, 200, IX_PANEL);
    sky();
    rows(sn_scene_maps + scene * SN_SCENE_COLS * SN_SCENE_ROWS, 8, 9, 0, 0);
    box(40, PLAY_Y + 28, 240, 84, IX_PANEL);
    if (caught) {
        centred(PLAY_Y + 36, target == BOSS ? "IL VESUVIO TACE!" : "SPIRITO CATTURATO!", GREEN);
        sprite(sn_trap_pixels, w_props, SN_TRAP_W, SN_TRAP_H, 4, 1, 0, 148, PLAY_Y + 122);
        if ((tick_no & 4) != 0) box(152, PLAY_Y + 118, 16, 2, IX_CONE);
    } else {
        centred(PLAY_Y + 36, "FUGA ECTOPLASMICA!", RED);
    }
    text(72, PLAY_Y + 56, caught ? "COMPENSO" : "DANNI", CYAN);
    text(176 + number(176, PLAY_Y + 56, reward, caught ? WHITE : RED), PLAY_Y + 56, "K", WHITE);
    text(72, PLAY_Y + 70, "CASSA", CYAN);
    text(176 + number(176, PLAY_Y + 70, cash, WHITE), PLAY_Y + 70, "K", WHITE);
    text(72, PLAY_Y + 84, "ENERGIA PK", CYAN);
    number(176, PLAY_Y + 84, pk, pk >= 70 ? RED : WHITE);
    text(72, PLAY_Y + 98, "PUNTI", CYAN);
    number(176, PLAY_Y + 98, score, YELLOW);
    top_band(haunt_name(target), YELLOW);
    bottom_band();
}

static void draw_over(void) {
    sky();
    if (!dawn) stars();
    far_vesuvius(196, PLAY_Y + 41);
    rows(sn_scene_maps + SN_SCENE_COLS * SN_SCENE_ROWS, 0, 9, 0, 0);
    if (ending == END_SAVED) {
        sprite(sn_fiat_pixels, w_fiat, SN_FIAT_W, SN_FIAT_H, 4, 1, 0, (scroll % 420) - 80, PLAY_Y + 116);
    } else {
        ghost_colours();
        sprite(spirit_pixels(spirit), w_ghost, SN_GHOST0_W, SN_GHOST0_H, 4, 1, 0,
               140 + wave16[(tick_no >> 2) & 15] * 4, PLAY_Y + 74 + wave16[(tick_no >> 1) & 15] / 2);
    }
    box(32, PLAY_Y + 14, 256, 50, IX_PANEL);
    if (ending == END_SAVED) centred(PLAY_Y + 20, "NAPOLI E' SALVA!", GREEN);
    else if (ending == END_BROKE) centred(PLAY_Y + 20, "CASSA VUOTA: SI CHIUDE", RED);
    else centred(PLAY_Y + 20, "NAPOLI E' DEGLI SPIRITI", RED);
    text(80, PLAY_Y + 34, "PUNTI", CYAN);
    number(144, PLAY_Y + 34, score, WHITE);
    text(80, PLAY_Y + 46, "RECORD", CYAN);
    number(144, PLAY_Y + 46, best, YELLOW);
    top_band(ending == END_SAVED ? "ALBA SUL GOLFO" : "FINE DEL TURNO", YELLOW);
    bottom_band();
    centred(HUD_Y + 3, "A  NUOVO TURNO   B  TITOLO", WHITE);
    centred(HUD_Y + 13, "SELECT  CLASSIFICA", CYAN);
}

void spiriti_napoli97_draw(void) {
    if (palette_dirty) palette_apply();
    animate();
    if (state == ST_TITLE) draw_title();
    else if (state == ST_MAP) draw_map();
    else if (state == ST_DRIVE) draw_drive();
    else if (state == ST_CAPTURE) draw_capture();
    else if (state == ST_RESULT) draw_result();
    else draw_over();
}

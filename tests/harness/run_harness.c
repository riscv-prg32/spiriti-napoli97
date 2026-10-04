/*
 * Host harness for Spiriti! Napoli '97.
 *
 * It includes the cartridge source and supplies the PRG32 calls with a
 * software model of both display back ends at once:
 *
 *   - `rgb` : QEMU's RGB565 surface, where an indexed sprite writes its own
 *             palette colours and indexed primitives look the palette up;
 *   - `idx` : the ESP32-C6 8-bit framebuffer, where every sprite colour is
 *             mapped to a 6x6x6 system-cube cell and expanded through the
 *             system palette when the frame is presented.
 *
 * A bot then plays the whole night shift. The harness asserts that the two
 * back ends show identical pixels whenever no fade or flash is running, that
 * every call is within the firmware's limits, that the game can be won, and
 * that the failure paths work. With SPIRITI_SHOTS=<dir> it also dumps frames
 * as PPM for tools/render_screens.py.
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../game.c"
#include "font8.h"

#define FB_W 320
#define FB_H 200

static uint16_t rgb[FB_W * FB_H];
static uint8_t idx[FB_W * FB_H];
static uint16_t sys_pal[256];
static uint32_t pad, clock_ms, frames, sprite_draws, max_sprite_draws, prim_draws, max_prim_draws;
static int notes_on[8], note_events, track_now = -1, tracks_started, pans_left, pans_right, tempo_calls, tempo_min = 999, tempo_max;
static uint32_t submitted_score;
static int submissions, scoreboards;
static const char *shot_dir;

/* ---- the firmware's palette model -------------------------------------- */
static uint16_t default_colour(unsigned i) {
    static const uint16_t named[16] = {0x0000, 0xffff, 0xf800, 0x07e0, 0x001f, 0xffe0, 0x07ff, 0xf81f,
                                       0x8410, 0xc618, 0x8000, 0x0400, 0x0010, 0x8400, 0x0410, 0x8010};
    unsigned v, gray;
    if (i < 16) return named[i];
    if (i < 232) {
        v = i - 16;
        return (uint16_t)((((v / 36) * 31 / 5) << 11) | ((((v / 6) % 6) * 63 / 5) << 5) | ((v % 6) * 31 / 5));
    }
    gray = (i - 232) * 255 / 23;
    return (uint16_t)(((gray * 31 / 255) << 11) | ((gray * 63 / 255) << 5) | (gray * 31 / 255));
}

static uint8_t index_for(uint16_t c) {
    unsigned i;
    for (i = 0; i < 8; i++) if (c == default_colour(i)) return (uint8_t)i;
    return (uint8_t)(16 + ((c >> 11) * 5 / 31) * 36 + (((c >> 5) & 63) * 5 / 63) * 6 + ((c & 31) * 5 / 31));
}

static void put(int x, int y, uint16_t colour, uint8_t index) {
    if (x < 0 || y < 0 || x >= FB_W || y >= FB_H) return;
    rgb[y * FB_W + x] = colour;
    idx[y * FB_W + x] = index;
}

/* ---- PRG32 calls -------------------------------------------------------- */
uint32_t prg32_input_read(void) { return pad; }
uint32_t prg32_ticks_ms(void) { return clock_ms; }
uint32_t prg32_random_number(uint32_t min, uint32_t max) { assert(max > min); return min + 12345u % (max - min); }
void prg32_band_set_game_info(const char *text) { assert(strlen(text) <= 40); }

prg32_audio_mode_t prg32_audio_get_mode(void) { return PRG32_AUDIO_MODE_STEREO; }
void prg32_audio_play_track(uint16_t track_id) { assert(track_id < 10); track_now = track_id; tracks_started++; }
void prg32_audio_set_tempo(uint16_t bpm) {
    assert(bpm >= 30 && bpm <= 300 && track_now >= 0);
    tempo_calls++;
    if (bpm < tempo_min) tempo_min = bpm;
    if (bpm > tempo_max) tempo_max = bpm;
}
void prg32_audio_note_on_pan(uint8_t channel, uint8_t instrument, uint8_t note, uint8_t volume, int8_t pan) {
    assert(channel >= 4 && channel < 8);              /* voices 0-3 belong to the tracker */
    assert(instrument >= 4 && instrument < 10 && note > 0 && note < 128 && volume > 0);
    assert(pan >= -64 && pan <= 63);
    if (pan < -8) pans_left++;
    if (pan > 8) pans_right++;
    notes_on[channel] = 1;
    note_events++;
}
void prg32_audio_note_off(uint8_t channel) { assert(channel >= 4 && channel < 8); notes_on[channel] = 0; }

int prg32_score_submit_current_player(const char *game, uint32_t value) {
    assert(!strcmp(game, "spiriti-napoli97"));
    if (value > submitted_score) submitted_score = value;
    submissions++;
    return 0;
}
int prg32_scoreboard_show(const char *game, const char *title) {
    assert(!strcmp(game, "spiriti-napoli97") && strlen(title) < 32);
    scoreboards++;
    clock_ms += 5000;                                  /* a modal screen: time passes */
    return 0;
}

void prg32_palette_set(uint8_t index, uint16_t colour) {
    assert(index >= 8 || colour == default_colour(index));     /* the eight named colours keep their values */
    sys_pal[index] = colour;
}
void prg32_gfx_rect_indexed(int x, int y, int w, int h, uint8_t index) {
    int i, j;
    assert(w > 0 && h > 0 && x >= 0 && y >= 0 && x + w <= FB_W && y + h <= FB_H);
    /* Any entry may be used: pictures draw with the cube cells the scene has programmed. */
    prim_draws++;
    for (j = 0; j < h; j++) for (i = 0; i < w; i++) put(x + i, y + j, sys_pal[index], index);
}
void prg32_gfx_text8(int x, int y, const char *s, uint16_t fg, uint16_t bg) {
    assert(index_for(fg) < 8 && bg == SN_UI_NAVY);     /* named ink on the navy panel */
    assert(x >= 0 && y >= 0 && y + 8 <= FB_H && x + (int)strlen(s) * 8 <= FB_W);
    for (; *s; s++, x += 8) {
        unsigned ch = (unsigned char)*s;
        int row, col;
        assert(ch >= 32 && ch < 127);
        for (row = 0; row < 8; row++)
            for (col = 0; col < 8; col++) {
                uint16_t c = (harness_font8[ch - 32][row] & (0x80u >> col)) ? fg : bg;
                put(x + col, y + row, c, index_for(c));
            }
    }
    prim_draws++;
}
void prg32_sprite_draw_indexed(int x, int y, const prg32_indexed_sprite_t *s, uint32_t frame) {
    unsigned bpp = s->bits_per_pixel, px, py;
    size_t frame_bits = (size_t)s->width * s->height * bpp;
    const uint8_t *data;
    assert(bpp == 1 || bpp == 2 || bpp == 4);
    assert(s->palette_count <= (1u << bpp) && s->transparent_index < (int)s->palette_count);
    assert(frame < s->frame_count);                    /* the firmware draws nothing for a frame out of range */
    assert(frame_bits % 8 == 0);
    assert(x > -400 && x < 720 && y > -200 && y < 400);
    data = s->pixels + frame * (frame_bits / 8);
    sprite_draws++;
    for (py = 0; py < s->height; py++)
        for (px = 0; px < s->width; px++) {
            size_t bit = ((size_t)py * s->width + px) * bpp;
            unsigned v = (data[bit / 8] >> (8 - bpp - bit % 8)) & ((1u << bpp) - 1);
            if (v >= s->palette_count || (int)v == s->transparent_index) continue;
            put(x + (int)px, y + (int)py, s->palette[v], index_for(s->palette[v]));
        }
}

static int backends_differ(void) {
    int i, n = 0;
    for (i = 0; i < FB_W * FB_H; i++)
        if (sys_pal[idx[i]] != rgb[i]) {
            if (!n) fprintf(stderr, "first at (%d,%d): QEMU %04x, ESP32-C6 entry %u = %04x\n", i % FB_W, i / FB_W,
                            (unsigned)rgb[i], (unsigned)idx[i], (unsigned)sys_pal[idx[i]]);
            n++;
        }
    return n;
}

static void dump(const char *name) {
    char path[512];
    FILE *f;
    int i;
    if (!shot_dir) return;
    snprintf(path, sizeof(path), "%s/%s.ppm", shot_dir, name);
    f = fopen(path, "wb");
    assert(f);
    fprintf(f, "P6\n%d %d\n255\n", FB_W, FB_H);
    for (i = 0; i < FB_W * FB_H; i++) {
        uint16_t c = sys_pal[idx[i]];                  /* what the ESP32-C6 panel shows */
        fputc((c >> 11) * 255 / 31, f);
        fputc(((c >> 5) & 63) * 255 / 63, f);
        fputc((c & 31) * 255 / 31, f);
    }
    fclose(f);
}

/* What the firmware does after the cartridge's draw callback. */
static void present(void) {
    int normal = fade == 16 && flash == 0;
    frames++;
    if (sprite_draws > max_sprite_draws) max_sprite_draws = sprite_draws;
    if (prim_draws > max_prim_draws) max_prim_draws = prim_draws;
    assert(sprite_draws <= 260 && prim_draws <= 2600);
    if (normal && frames > 1) {
        int bad = backends_differ();
        if (bad) {
            fprintf(stderr, "frame %u state %d scene %d: %d pixels differ between ESP32-C6 and QEMU\n",
                    (unsigned)frames, (int)state, (int)scene, bad);
            dump("mismatch");
            exit(1);
        }
    }
    sprite_draws = prim_draws = 0;
}

/* ---- driving ------------------------------------------------------------ */
static void frame(uint32_t buttons) {
    pad = buttons;
    clock_ms += TICK_MS;
    spiriti_napoli97_update();
    spiriti_napoli97_draw();
    present();
}
static void frames_n(uint32_t buttons, int n) { while (n--) frame(buttons); }
static void tap(uint32_t buttons) { frame(buttons); frame(0); }
static void settle(void) { int guard = 0; do frame(0); while ((leaving || fade < 16) && ++guard < 60); }

/* Drive: keep out from under the flying spirits, hoover the puddles, pick up the coffee. */
static uint32_t drive_bot(void) {
    static uint32_t last;
    uint32_t in = PRG32_BTN_RIGHT;
    int danger[3] = {0, 0, 0}, gain[3] = {0, 0, 0}, i, lane, want = car_lane, best_gain = -1;
    for (i = 0; i < MAX_FLYERS; i++)
        if (flyers[i].on && !flyers[i].dropped && flyers[i].x < car_x + 150) danger[flyers[i].lane] = 1;
    for (i = 0; i < MAX_DROPS; i++)
        if (drops[i].on) danger[drops[i].lane] = 1;
    for (i = 0; i < MAX_OBJS; i++)
        if (objs[i].on && objs[i].x > car_x + 70 && objs[i].x < car_x + 240) gain[objs[i].lane] += 300 - objs[i].x;
    for (lane = 0; lane < 3; lane++) {
        int score_lane = gain[lane] - absi(lane - car_lane);
        if (danger[lane]) continue;
        if (score_lane > best_gain) { best_gain = score_lane; want = lane; }
    }
    if (want < car_lane && !(last & PRG32_BTN_UP)) in |= PRG32_BTN_UP;
    if (want > car_lane && !(last & PRG32_BTN_DOWN)) in |= PRG32_BTN_DOWN;
    last = in;
    return in;
}
static int cooling;
static int bursts(void) {
    if (heat >= 88) cooling = 1;
    if (heat <= 30) cooling = 0;
    return !cooling && !bolt && (tick_no % 96u) < 88u;
}
/* A district: keep the trap under the spirit, fire in bursts so the pack never vents. */
static uint32_t trap_bot(void) {
    uint32_t in = 0;
    int centre = ghost_x + enemy_w() / 2, trap = trap_x + SN_TRAP_W / 2;
    if (trap < centre - 6) in |= PRG32_BTN_RIGHT;
    if (trap > centre + 6) in |= PRG32_BTN_LEFT;
    if (bursts()) in |= PRG32_BTN_A;
    return in;
}
/* The villa: fire in bursts and step out from under whatever is falling. */
static uint32_t pack_bot(void) {
    uint32_t in = 0;
    int i, me = hero_x + 16;
    for (i = 0; i < MAX_DROPS; i++) {
        int aim = drops[i].on ? (drops[i].x16 + drops[i].vx16 * ((drops[i].ground - drops[i].y) / 5)) >> 4 : -999;
        if (absi(aim - me) < 30) in |= (aim >= me && hero_x > 40) || hero_x > 250 ? PRG32_BTN_LEFT : PRG32_BTN_RIGHT;
    }
    if (bursts()) in |= PRG32_BTN_A;
    return in;
}
/* The piazza: bind the giant with the rays, get under him, open the trap when he is bound. */
static uint32_t car_bot(void) {
    static uint32_t last;
    uint32_t in = 0;
    int centre = ghost_x + GIANT_W / 2, me = hero_x + SN_FIAT_W / 2, i, dodge = 0;
    for (i = 0; i < MAX_DROPS; i++) {
        int aim = drops[i].on ? (drops[i].x16 + drops[i].vx16 * ((drops[i].ground - drops[i].y) / 5)) >> 4 : -999;
        if (absi(aim - me) < 44 && !stun) { in |= (aim >= me && hero_x > 60) || hero_x > 200 ? PRG32_BTN_LEFT : PRG32_BTN_RIGHT; dodge = 1; }
    }
    if (!dodge) {
        if (me < centre - 10) in |= PRG32_BTN_RIGHT;
        if (me > centre + 10) in |= PRG32_BTN_LEFT;
    }
    if (stun) { if (absi(me - centre) < 40 && !trap_cd && !(last & PRG32_BTN_B)) in |= PRG32_BTN_B; }
    else if (bursts()) in |= PRG32_BTN_A;
    last = in;
    return in;
}

static const char *shot_name(int haunt) {
    return haunt == 0 ? "04-centro-gesu-nuovo" : haunt == 1 ? "05-mergellina-castel-dell-ovo" :
           haunt == 2 ? "06-vomero-sant-elmo" : haunt == 3 ? "07-porto-maschio-angioino" :
           haunt == 4 ? "08-fuorigrotta-stadio" : haunt == 5 ? "09-capodimonte-reggia" :
           haunt == VILLA ? "10-villa-doria-d-angri" : "14-piazza-del-plebiscito";
}
static void run_drive(int haunt, int shots) {
    int guard, shot = 0;
    assert(state == ST_DRIVE && track_now == TRACK_DRIVE && notes_on[V_LOW] && target == haunt);
    for (guard = 0; guard < 4000 && state == ST_DRIVE; guard++) {
        int flying = flyers[0].on || flyers[1].on;
        frame(drive_bot());
        if (shots && !shot && distance > 500 && flying && objs[0].on && !leaving && fade == 16 && !flash) {
            dump(haunt == PIAZZA ? "13-corsa-al-plebiscito" : "03-lungomare");
            shot = 1;
        }
    }
    assert(state == ST_CAPTURE && !notes_on[V_LOW] && !notes_on[V_SIREN] && scene == haunt);
}
static void run_fight(int haunt, int shots) {
    int guard, shot = 0;
    cooling = 0;
    assert(fight == (haunt == PIAZZA ? FIGHT_CAR : haunt == VILLA ? FIGHT_PACK : FIGHT_TRAP));
    assert(track_now == (haunt == PIAZZA ? TRACK_GIANT : haunt == VILLA ? TRACK_GUARDIAN : TRACK_CAPTURE));
    assert(spirit == (haunt == PIAZZA ? -1 : haunt == VILLA ? 6 : haunt_spirit(haunt)));
    for (guard = 0; guard < 9000 && state == ST_CAPTURE; guard++) {
        frame(fight == FIGHT_CAR ? car_bot() : fight == FIGHT_PACK ? pack_bot() : trap_bot());
        if (shots && !shot && beam_on && !leaving && fade == 16 && !flash && !bolt && !shake &&
            (fight == FIGHT_TRAP ? meter > 45 : fight == FIGHT_PACK ? boss_hp < 110 && drops[0].on : meter > 60)) {
            dump(shot_name(haunt));
            shot = 1;
        }
        if (shots && fight == FIGHT_CAR && stun == 58 && boss_hp == 3) dump("15-pulcinella-legato");
    }
    assert(state == ST_RESULT && caught && cleared[haunt] && !notes_on[V_BEAM]);
    assert(track_now == TRACK_CAUGHT);
}
static void run_job(int haunt, int shots) {
    int guard, before = cash;
    assert(state == ST_MAP && haunt_open(haunt));
    for (guard = 0; selected != haunt && guard < 20; guard++) tap(PRG32_BTN_RIGHT);
    assert(selected == haunt);
    if (shots && haunt == 0) dump("02-mappa");
    tap(PRG32_BTN_A);
    assert(cash == before - COST && target == haunt);
    settle();
    run_drive(haunt, shots && haunt == 0);
    run_fight(haunt, shots);
    frames_n(0, 20);
    if (shots && haunt == 0) dump("21-catturato");
}

static void play_night(void) {
    int haunt, guard;
    frames_n(0, 40);
    assert(state == ST_TITLE && track_now == TRACK_TITLE && fade == 16);
    dump("01-titolo");
    tap(PRG32_BTN_SELECT);
    assert(scoreboards == 1 && state == ST_TITLE);     /* the modal scoreboard does not skip game time */
    frames_n(0, 3);
    tap(PRG32_BTN_A);
    settle();
    assert(state == ST_MAP && track_now == TRACK_MAP && cash == START_CASH && score == 0);
    assert(!haunt_open(VILLA) && !haunt_open(PIAZZA)); /* the villa wakes only when the districts are clear */
    for (haunt = 0; haunt < DISTRICTS; haunt++) {
        run_job(haunt, 1);
        frames_n(0, 200);
        assert(state == ST_MAP && jobs_done == haunt + 1);
    }
    assert(haunt_open(VILLA) && !haunt_open(PIAZZA) && selected == VILLA);
    run_job(VILLA, 1);
    /* The guardian is gone; the voice asks for the form of the destructor. */
    for (guard = 0; guard < 400 && state != ST_OMEN; guard++) frame(0);
    assert(state == ST_OMEN && track_now == TRACK_OMEN && scene == PIAZZA);
    frames_n(0, 150);
    dump("11-scegli-la-forma");
    frames_n(0, 120);
    assert(state == ST_OMEN && omen_t > OMEN_REVEAL);
    dump("12-pulcinella");
    {
        int before = cash;
        for (guard = 0; guard < 400 && state != ST_DRIVE; guard++) frame(0);
        assert(state == ST_DRIVE && target == PIAZZA && cash == before);   /* this ride is on the house */
    }
    run_drive(PIAZZA, 1);
    run_fight(PIAZZA, 1);
    for (guard = 0; guard < 400 && state != ST_OVER; guard++) frame(0);
    assert(state == ST_OVER && ending == END_SAVED && dawn && track_now == TRACK_PARADE);
    assert(submissions == 1 && submitted_score == (uint32_t)score && best == score);
    frames_n(0, 40);
    dump("16-parata");
    printf("night shift: %u frames, score %d, cash %dK, PK %d\n", (unsigned)frames, score, cash, pk);
    tap(PRG32_BTN_B);
    settle();
    assert(state == ST_TITLE);
}

static void start_capture(int haunt) {
    if (state != ST_TITLE) { enter(ST_TITLE); fade = 16; leaving = 0; }
    frame(0);
    tap(PRG32_BTN_A);
    settle();
    assert(state == ST_MAP);
    target = selected = haunt;
    cups = slimed = cleaned = 0;
    go(ST_CAPTURE);
    settle();
    assert(state == ST_CAPTURE);
}

static void check_rules(void) {
    int i, before;

    /* Holding the beam overheats the pack: it vents, the beam stops, the note is released. */
    start_capture(0);
    for (i = 0; i < 200 && !vent; i++) { meter = 0; frame(PRG32_BTN_A); }
    frames_n(PRG32_BTN_A, 3);
    assert(vent && !beam_on && state == ST_CAPTURE);
    assert(!notes_on[V_BEAM]);
    dump("17-sfiato");
    for (i = 0; i < 200 && vent; i++) frame(PRG32_BTN_A);
    assert(!vent && heat < 50 && beam_on);        /* cooled: the beam fires again */

    /* A spirit left alone runs out the clock: the job fails, costs money and raises the PK energy. */
    start_capture(0);
    before = cash;
    i = pk;
    patience = 20;
    frames_n(0, 30);
    settle();
    assert(state == ST_RESULT && !caught && cash == before - 150 && pk >= i + 10 && track_now == TRACK_ESCAPED);
    dump("18-fuga");
    frames_n(0, 200);
    assert(state == ST_MAP && !cleared[0]);

    /* B gives the job up. */
    start_capture(1);
    tap(PRG32_BTN_B);
    settle();
    assert(state == ST_RESULT && !caught);

    /* An empty till ends the shift and the score is kept. */
    start_capture(0);
    submissions = 0;
    cash = 300;
    patience = 5;
    frames_n(0, 300);
    assert(state == ST_OVER && ending == END_BROKE && submissions == 1);
    dump("19-cassa-vuota");

    /* So does a city saturated with psychokinetic energy. */
    start_capture(0);
    submissions = 0;
    pk = 99; pk_clock = PK_PERIOD - 1;
    frames_n(0, 40);
    assert(state == ST_OVER && ending == END_LOST && submissions == 1);
    tap(PRG32_BTN_A);
    settle();
    assert(state == ST_MAP && pk == 20 && cash == START_CASH);

    /* On the road: a puddle driven over is cleaned, one left behind is not forgotten. */
    target = selected = 0;
    go(ST_DRIVE);
    settle();
    assert(state == ST_DRIVE);
    for (i = 0; i < MAX_OBJS; i++) objs[i].on = 0;
    spawn_in = fly_in = 100000;
    objs[0].on = 1; objs[0].kind = OBJ_PUDDLE; objs[0].lane = (uint8_t)car_lane; objs[0].x = (int16_t)(car_x + 90);
    before = score;
    frames_n(0, 30);
    assert(cleaned == 1 && !objs[0].on && !slip && score == before + 20);
    objs[0].on = objs[1].on = 1; objs[0].kind = objs[1].kind = OBJ_PUDDLE;
    objs[0].lane = objs[1].lane = (uint8_t)((car_lane + 1) % 3); objs[0].x = 40; objs[1].x = 60;
    i = pk; pk_clock = 0;
    frames_n(0, 40);
    assert(missed == 2 && pk == i + 1 && cleaned == 1);
    objs[1].on = 1; objs[1].kind = OBJ_CUP; objs[1].lane = (uint8_t)car_lane; objs[1].x = (int16_t)(car_x + 90);
    frames_n(0, 40);
    assert(cups == 1 && !objs[1].on);

    /* A spirit flying over the car's lane slimes it; one lane away it misses. */
    flyers[0].on = 1; flyers[0].dropped = 0; flyers[0].lane = (uint8_t)car_lane; flyers[0].x = (int16_t)(car_x + 100);
    i = pk; pk_clock = 0;
    for (before = 0; before < 60 && !slip; before++) frame(0);
    frames_n(0, 6);
    assert(slip && speed < 4 && slimed == 1 && pk == i + 2);
    dump("20-scivolata");
    frames_n(0, 40);
    flyers[0].on = 1; flyers[0].dropped = 0; flyers[0].lane = (uint8_t)((car_lane + 1) % 3); flyers[0].x = (int16_t)(car_x + 100);
    frames_n(0, 60);
    assert(slimed == 1 && flyers[0].dropped);
    tap(PRG32_BTN_UP);
    frames_n(0, 12);
    assert(car_lane == 0 && car_y == lane_top(0));
    tap(PRG32_BTN_B);
    settle();
    assert(state == ST_MAP && !notes_on[V_LOW]);

    /* The villa: standing under the guardian's fire scorches the pack and costs time. */
    jobs_done = DISTRICTS;
    for (i = 0; i < DISTRICTS; i++) cleared[i] = 1;
    target = selected = VILLA;
    go(ST_CAPTURE);
    settle();
    assert(fight == FIGHT_PACK && boss_hp == GUARDIAN_HP);
    before = patience;
    for (i = 0; i < 300 && !heat; i++) frame(0);
    assert(heat > 0 && before - patience >= i + 80 && state == ST_CAPTURE);
    i = boss_hp;
    frames_n(PRG32_BTN_A, 10);
    assert(boss_hp < i);                              /* only the beam wears it down */
    patience = 3;
    frames_n(0, 20);
    settle();
    assert(state == ST_RESULT && !caught && !cleared[VILLA]);
    frames_n(0, 200);
    assert(state == ST_MAP && haunt_open(VILLA));     /* a lost fight can be called again from the map */

    /* The piazza: opening the trap on an unbound giant only loosens the hold. */
    cleared[VILLA] = 1; jobs_done = DISTRICTS + 1;
    target = selected = PIAZZA;
    go(ST_CAPTURE);
    settle();
    assert(fight == FIGHT_CAR && boss_hp == 3);
    meter = 60;
    tap(PRG32_BTN_B);
    assert(boss_hp == 3 && meter <= 31 && trap_cd > 0);
    for (i = 0; i < 400 && !stun; i++) { heat = 0; drops[0].on = drops[1].on = drops[2].on = 0; frame(PRG32_BTN_A); }
    assert(stun);
    hero_x = clampi(ghost_x + GIANT_W / 2 - SN_FIAT_W / 2, 0, 320 - SN_FIAT_W);
    trap_cd = 0;
    tap(PRG32_BTN_B);
    assert(boss_hp == 2 && !stun && meter == 0);      /* bound and under the trap: one round won */
    patience = 3;
    frames_n(0, 20);
    settle();
    assert(state == ST_RESULT && !caught);
    frames_n(0, 200);
    assert(state == ST_MAP && haunt_open(PIAZZA) && selected == PIAZZA);

    /* A press that arrives between two simulation steps is not lost. */
    pad = PRG32_BTN_B;
    clock_ms += 5;
    spiriti_napoli97_update();
    spiriti_napoli97_draw();
    present();
    settle();
    assert(state == ST_TITLE);

    /* A slow frame runs several steps; a very long stall is capped. */
    {
        uint32_t before_tick = tick_no;
        pad = 0;
        clock_ms += 3 * TICK_MS;
        spiriti_napoli97_update();
        assert(tick_no == before_tick + 3);
        clock_ms += 5000;
        spiriti_napoli97_update();
        assert(tick_no == before_tick + 7);
        spiriti_napoli97_draw();
        present();
    }
}

int main(void) {
    unsigned i;
    shot_dir = getenv("SPIRITI_SHOTS");
    for (i = 0; i < 256; i++) sys_pal[i] = default_colour(i);
    for (i = 0; i < 8; i++) sys_pal[i] = 0x1234;       /* as if another cartridge had left its palette behind */
    clock_ms = 1000;
    spiriti_napoli97_init();
    play_night();
    check_rules();
    assert(tracks_started > 20 && note_events > 200);
    assert(tempo_calls > 100 && tempo_min < 130 && tempo_max > 160);    /* the music follows the action */
    assert(pans_left > 20 && pans_right > 20);         /* effects really move across the stereo field */
    printf("OK: %u frames, both display back ends identical, at most %u sprite and %u primitive draws per frame\n",
           (unsigned)frames, (unsigned)max_sprite_draws, (unsigned)max_prim_draws);
    return 0;
}

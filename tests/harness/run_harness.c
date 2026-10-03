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
static int notes_on[8], note_events, track_now = -1, tracks_started, pans_left, pans_right;
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
void prg32_audio_play_track(uint16_t track_id) { assert(track_id < 8); track_now = track_id; tracks_started++; }
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
    assert(index < 16 || index >= 232);                /* never a cube cell the art may have reprogrammed */
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
    assert(sprite_draws <= 260 && prim_draws <= 480);
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

/* Drive: stay out of the slime, pick up the coffee. */
static uint32_t drive_bot(void) {
    static uint32_t last;
    uint32_t in = PRG32_BTN_RIGHT;
    int want = car_lane, i, lane, best_lane = -1;
    for (lane = 0; lane < 3; lane++) {
        int try = (car_lane + lane) % 3, blocked = 0;
        for (i = 0; i < MAX_OBJS; i++)
            if (objs[i].on && objs[i].kind == OBJ_SLIME && objs[i].lane == try && objs[i].x > car_x - 30 && objs[i].x < car_x + 170)
                blocked = 1;
        if (!blocked) { best_lane = try; break; }
    }
    if (best_lane >= 0) want = best_lane;
    for (i = 0; i < MAX_OBJS; i++)
        if (objs[i].on && objs[i].kind == OBJ_CUP && objs[i].x > car_x + 80 && best_lane == car_lane) want = objs[i].lane;
    if (want < car_lane && !(last & PRG32_BTN_UP)) in |= PRG32_BTN_UP;
    if (want > car_lane && !(last & PRG32_BTN_DOWN)) in |= PRG32_BTN_DOWN;
    last = in;
    return in;
}
/* Capture: keep the trap under the spirit, fire in bursts so the pack never vents. */
static uint32_t capture_bot(void) {
    static int cooling;
    uint32_t in = 0;
    int centre = ghost_x + spirit_w() / 2, trap = trap_x + SN_TRAP_W / 2;
    if (trap < centre - 6) in |= PRG32_BTN_RIGHT;
    if (trap > centre + 6) in |= PRG32_BTN_LEFT;
    if (heat >= 90) cooling = 1;
    if (heat <= 30) cooling = 0;
    if (!cooling && !bolt && (tick_no % 96u) < 90u) in |= PRG32_BTN_A;
    return in;
}

static void run_job(int haunt, int shots) {
    char name[40];
    int guard, shot_drive = 0, shot_capture = 0;
    assert(state == ST_MAP && haunt_open(haunt));
    for (guard = 0; selected != haunt && guard < 20; guard++) tap(PRG32_BTN_RIGHT);
    assert(selected == haunt);
    if (shots && haunt == 0) dump("02-mappa");
    {
        int before = cash;
        tap(PRG32_BTN_A);
        assert(cash == before - COST && target == haunt);
    }
    settle();
    assert(state == ST_DRIVE && track_now == TRACK_DRIVE && notes_on[V_LOW]);
    for (guard = 0; guard < 4000 && state == ST_DRIVE; guard++) {
        frame(drive_bot());
        if (shots && haunt == 0 && !shot_drive && distance > 900 && !leaving && fade == 16 && !flash) { dump("03-lungomare"); shot_drive = 1; }
    }
    assert(state == ST_CAPTURE && !notes_on[V_LOW] && !notes_on[V_SIREN]);
    assert(track_now == (haunt == BOSS ? TRACK_BOSS : TRACK_CAPTURE));
    assert(scene == haunt && spirit == haunt_spirit(haunt));
    for (guard = 0; guard < 6000 && state == ST_CAPTURE; guard++) {
        frame(capture_bot());
        if (shots && !shot_capture && beam_on && meter > 45 && !leaving && fade == 16 && !flash && !bolt) {
            snprintf(name, sizeof(name), "%02d-%s", 4 + haunt, haunt == 0 ? "centro" : haunt == 1 ? "mergellina" :
                     haunt == 2 ? "vomero" : haunt == 3 ? "porto" : haunt == 4 ? "fuorigrotta" :
                     haunt == 5 ? "capodimonte" : "vesuvio");
            dump(name);
            shot_capture = 1;
        }
    }
    assert(state == ST_RESULT && caught && cleared[haunt] && !notes_on[V_BEAM]);
    assert(track_now == TRACK_CAUGHT);
    frames_n(0, 20);
    if (shots && haunt == 0) dump("11-catturato");
}

static void play_night(void) {
    int haunt;
    frames_n(0, 40);
    assert(state == ST_TITLE && track_now == TRACK_TITLE && fade == 16);
    dump("01-titolo");
    tap(PRG32_BTN_SELECT);
    assert(scoreboards == 1 && state == ST_TITLE);     /* the modal scoreboard does not skip game time */
    frames_n(0, 3);
    tap(PRG32_BTN_A);
    settle();
    assert(state == ST_MAP && track_now == TRACK_MAP && cash == START_CASH && score == 0);
    assert(!haunt_open(BOSS));                         /* the volcano wakes only when the districts are clear */
    for (haunt = 0; haunt < HAUNTS; haunt++) {
        run_job(haunt, 1);
        frames_n(0, 200);
        if (haunt < BOSS) { assert(state == ST_MAP && jobs_done == haunt + 1); }
    }
    assert(state == ST_OVER && ending == END_SAVED && dawn && track_now == TRACK_DAWN);
    assert(submissions == 1 && submitted_score == (uint32_t)score && best == score);
    frames_n(0, 30);
    dump("12-alba");
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
    cups = slimed = 0;
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
    dump("13-sfiato");
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
    dump("14-fuga");
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
    dump("15-cassa-vuota");

    /* So does a city saturated with psychokinetic energy. */
    start_capture(0);
    submissions = 0;
    pk = 99; pk_clock = PK_PERIOD - 1;
    frames_n(0, 40);
    assert(state == ST_OVER && ending == END_LOST && submissions == 1);
    tap(PRG32_BTN_A);
    settle();
    assert(state == ST_MAP && pk == 20 && cash == START_CASH);

    /* Slime costs speed and feeds the PK energy; coffee is kept for the capture. */
    target = selected = 0;
    go(ST_DRIVE);
    settle();
    assert(state == ST_DRIVE);
    for (i = 0; i < MAX_OBJS; i++) objs[i].on = 0;
    spawn_in = 1000;
    objs[0].on = 1; objs[0].kind = OBJ_SLIME; objs[0].lane = (uint8_t)car_lane; objs[0].x = (int16_t)(car_x + 90);
    i = pk;
    pk_clock = 0;
    frames_n(0, 14);
    assert(slip && speed < 4 && slimed == 1 && pk == i + 2 && !objs[0].on);
    dump("16-scivolata");
    objs[1].on = 1; objs[1].kind = OBJ_CUP; objs[1].lane = (uint8_t)car_lane; objs[1].x = (int16_t)(car_x + 90);
    frames_n(0, 60);
    assert(cups == 1 && !objs[1].on);
    tap(PRG32_BTN_UP);
    frames_n(0, 12);
    assert(car_lane == 0 && car_y == PLAY_Y + 124 - SN_FIAT_H);
    tap(PRG32_BTN_B);
    settle();
    assert(state == ST_MAP && !notes_on[V_LOW]);

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
    assert(pans_left > 20 && pans_right > 20);         /* effects really move across the stereo field */
    printf("OK: %u frames, both display back ends identical, at most %u sprite and %u primitive draws per frame\n",
           (unsigned)frames, (unsigned)max_sprite_draws, (unsigned)max_prim_draws);
    return 0;
}

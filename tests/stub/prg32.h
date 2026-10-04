/* Minimal host-side copy of the PRG32 declarations this cartridge uses.
 * Constants and layouts mirror components/prg32/include/prg32.h; the real
 * headers stay authoritative and this file is never packed into a cartridge. */
#ifndef PRG32_H
#define PRG32_H
#include <stddef.h>
#include <stdint.h>

#define PRG32_BTN_LEFT (1u << 0)
#define PRG32_BTN_RIGHT (1u << 1)
#define PRG32_BTN_UP (1u << 2)
#define PRG32_BTN_DOWN (1u << 3)
#define PRG32_BTN_A (1u << 4)
#define PRG32_BTN_B (1u << 5)
#define PRG32_BTN_START (1u << 6)
#define PRG32_BTN_SELECT PRG32_BTN_START

typedef enum { PRG32_AUDIO_MODE_MONO = 1, PRG32_AUDIO_MODE_STEREO = 2 } prg32_audio_mode_t;

typedef struct {
    const uint8_t *pixels;
    const uint16_t *palette;
    uint16_t width;
    uint16_t height;
    uint16_t frame_count;
    uint16_t palette_count;
    uint8_t bits_per_pixel;
    int16_t transparent_index;
} prg32_indexed_sprite_t;

uint32_t prg32_input_read(void);
uint32_t prg32_ticks_ms(void);
uint32_t prg32_random_number(uint32_t min, uint32_t max);
void prg32_band_set_game_info(const char *text);

prg32_audio_mode_t prg32_audio_get_mode(void);
void prg32_audio_play_track(uint16_t track_id);
void prg32_audio_set_tempo(uint16_t bpm);
void prg32_audio_note_on_pan(uint8_t channel, uint8_t instrument, uint8_t note, uint8_t volume, int8_t pan);
void prg32_audio_note_off(uint8_t channel);

int prg32_score_submit_current_player(const char *game, uint32_t score);
int prg32_scoreboard_show(const char *game, const char *title);

void prg32_gfx_rect_indexed(int x, int y, int w, int h, uint8_t index);
void prg32_palette_set(uint8_t index, uint16_t rgb565);
void prg32_gfx_text8(int x, int y, const char *s, uint16_t fg, uint16_t bg);
void prg32_sprite_draw_indexed(int x, int y, const prg32_indexed_sprite_t *sprite, uint32_t frame);
#endif

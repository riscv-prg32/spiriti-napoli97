#ifndef PRG32_H
#define PRG32_H
#include <stdint.h>
#define PRG32_BTN_LEFT (1u<<0)
#define PRG32_BTN_RIGHT (1u<<1)
#define PRG32_BTN_UP (1u<<2)
#define PRG32_BTN_DOWN (1u<<3)
#define PRG32_BTN_A (1u<<4)
#define PRG32_BTN_B (1u<<5)
#define PRG32_BTN_SELECT (1u<<6)
#define PRG32_AUDIO_MODE_STEREO 2

typedef struct {
    const uint8_t *pixels;
    const uint16_t *palette;
    uint16_t width,height,frame_count,palette_count;
    uint8_t bits_per_pixel;
    int16_t transparent_index;
} prg32_indexed_sprite_t;

uint32_t prg32_ticks_ms(void); uint32_t prg32_input_read(void);
void prg32_gfx_clear(uint16_t); void prg32_gfx_rect(int,int,int,int,uint16_t); void prg32_gfx_text8(int,int,const char*,uint16_t,uint16_t);
void prg32_sprite_draw_indexed(int,int,const prg32_indexed_sprite_t*,uint16_t);
void prg32_sprite_draw_bitplanes(int,int,const prg32_indexed_sprite_t*,uint16_t);
void prg32_tile_define(uint8_t,const uint8_t*,uint16_t,uint16_t);
void prg32_playfield_clear(uint8_t,uint8_t); void prg32_playfield_put(uint8_t,uint8_t,uint8_t,uint8_t);
void prg32_playfield_scroll(uint8_t,int16_t,int16_t); void prg32_playfield_draw_dual(void);
void prg32_band_set_game_info(const char*); int prg32_audio_get_mode(void); void prg32_audio_play_track(uint16_t);
void prg32_audio_note_on_pan(uint8_t,uint8_t,uint8_t,uint8_t,int8_t); void prg32_audio_note_off(uint8_t);
int prg32_scoreboard_show(const char*,const char*); int prg32_score_submit_current_player(const char*,uint32_t);
#endif

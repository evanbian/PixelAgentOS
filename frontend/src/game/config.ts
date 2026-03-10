import Phaser from 'phaser';
import { OfficeScene } from './scenes/OfficeScene';
import { UIScene } from './scenes/UIScene';

// Tile dimensions (kept for compatibility)
export const TILE_SIZE = 32;
export const MAP_COLS = 24;
export const MAP_ROWS = 18;

export const GAME_WIDTH = MAP_COLS * TILE_SIZE;   // 768
export const GAME_HEIGHT = MAP_ROWS * TILE_SIZE;  // 576

// ── Asset paths ──────────────────────────────────────────────────────────────
export const ASSETS = {
  BG: '/assets/bg/office_bg.png',
  ROLE_SPRITES: {
    Developer:  '/assets/sprites/developer_sheet.png',
    Researcher: '/assets/sprites/researcher_sheet.png',
    Analyst:    '/assets/sprites/analyst_sheet.png',
    Writer:     '/assets/sprites/writer_sheet.png',
    Designer:   '/assets/sprites/designer_sheet.png',
    PM:         '/assets/sprites/pm_sheet.png',
    DevOps:     '/assets/sprites/default_sheet.png',
    QA:         '/assets/sprites/default_sheet.png',
  } as Record<string, string>,
};

// ── Sprite config ────────────────────────────────────────────────────────────
// Per-role spritesheet: 4 cols × 1 row, 64×64 per frame
// Frame 0: idle, 1: working, 2: thinking, 3: communicating
export const SPRITE_CONFIG = {
  FRAME_WIDTH: 64,
  FRAME_HEIGHT: 64,
  COLS: 4,
  ROWS: 1,
  DISPLAY_SCALE: 1.5,   // 64 * 1.3 ≈ 83px — proportional to workstation furniture
  PM_DISPLAY_SCALE: 0.9, // PM portrait at native 64px (front-facing, inherently larger feel)
};

export const STATUS_FRAME_INDEX: Record<string, number> = {
  idle: 0,
  working: 1,
  thinking: 2,
  communicating: 3,
};

// Twemoji-based status emotes (loaded as Phaser images with bubble background)
// Keys are Phaser texture keys matching preloaded assets in OfficeScene
export const STATUS_EMOTE_KEYS: Record<string, string> = {
  working: 'emote-lightning',
  thinking: 'emote-thought',
  communicating: 'emote-chat',
};

// Idle emote texture keys — one is picked at random every IDLE_EMOTE_INTERVAL ms
export const IDLE_EMOTE_KEYS = [
  'emote-gamepad', 'emote-coffee', 'emote-cat', 'emote-zzz',
  'emote-sparkles', 'emote-drink', 'emote-phone', 'emote-music',
];
export const IDLE_EMOTE_INTERVAL = 10000;  // ms between random idle emotes
export const IDLE_EMOTE_DURATION = 3000;   // ms each idle emote stays visible

// All emote assets to preload
export const EMOTE_ASSETS: Record<string, string> = {
  'emote-gamepad':   '/assets/emojis/gamepad.png',
  'emote-coffee':    '/assets/emojis/coffee.png',
  'emote-cat':       '/assets/emojis/cat.png',
  'emote-zzz':       '/assets/emojis/zzz.png',
  'emote-sparkles':  '/assets/emojis/sparkles.png',
  'emote-drink':     '/assets/emojis/drink.png',
  'emote-phone':     '/assets/emojis/phone.png',
  'emote-music':     '/assets/emojis/music.png',
  'emote-lightning':  '/assets/emojis/lightning.png',
  'emote-thought':   '/assets/emojis/thought.png',
  'emote-chat':      '/assets/emojis/chat.png',
};

export const DEFAULT_SPRITE_KEY = 'sprite-default';

export function getTextureKeyForRole(role: string): string {
  if (ASSETS.ROLE_SPRITES[role]) return `sprite-${role.toLowerCase()}`;
  return DEFAULT_SPRITE_KEY;
}

// ── Debug mode: show hit zone boundaries ─────────────────────────────────────
export const DEBUG_HIT_ZONES = false;

// ── Workstation positions (pixel coordinates matching background image) ───────
// Layout: 3 columns × 3 rows on the left side of the office
// Each entry: x,y = center of the chair area where agent sprite sits
// hitW, hitH = clickable area dimensions
//
// Y coordinates are calibrated to chair centers (BELOW desk surface, not ON it).
// X positions match actual desk column centers in the background image.
export const WORKSTATION_POSITIONS = [
  // Row 1 (top desks — positions verified interactively in-browser)
  { id: 'ws_0',  x: 178,  y: 172,  hitW: 90, hitH: 70 },
  { id: 'ws_1',  x: 352,  y: 172,  hitW: 90, hitH: 70 },
  { id: 'ws_2',  x: 448,  y: 172,  hitW: 90, hitH: 70 },
  // Row 2 (middle desks)
  { id: 'ws_3',  x: 110,  y: 302,  hitW: 90, hitH: 70 },
  { id: 'ws_4',  x: 292,  y: 302,  hitW: 90, hitH: 70 },
  { id: 'ws_5',  x: 474,  y: 302,  hitW: 90, hitH: 70 },
  // Row 3 (bottom desks)
  { id: 'ws_6',  x: 110,  y: 432,  hitW: 90, hitH: 70 },
  { id: 'ws_7',  x: 292,  y: 432,  hitW: 90, hitH: 70 },
  { id: 'ws_8',  x: 474,  y: 432,  hitW: 90, hitH: 70 },
];

// ── PM desk position (boss chair, right side) ───────────────────────────────
// PM agent always spawns here instead of a numbered workstation.
export const PM_DESK_POSITION = { x: 670, y: 195 };

// ── Interactive zones (pixel coords on background image) ─────────────────────
export const INTERACTIVE_ZONES = {
  WHITEBOARD:     { x: 635, y: 90, w: 180, h: 110 },
  PM_DESK:        { x: 660, y: 320, w: 140, h: 80 },
  FILING_CABINET: { x: 708, y: 385, w: 75, h: 105 },
  WATER_COOLER:   { x: 718, y: 440, w: 45, h: 65 },
  DOOR:           { x: 400, y: 548, w: 75, h: 30 },
};

export const gameConfig: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  width: GAME_WIDTH,
  height: GAME_HEIGHT,
  backgroundColor: '#1a1a2e',
  pixelArt: true,
  roundPixels: true,
  scene: [OfficeScene, UIScene],
  physics: {
    default: 'arcade',
    arcade: { debug: false },
  },
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
};

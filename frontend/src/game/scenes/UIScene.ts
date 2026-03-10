import Phaser from 'phaser';

export class UIScene extends Phaser.Scene {
  constructor() {
    super({ key: 'UIScene', active: true });
  }

  create() {
    // This scene overlays HUD elements on top of the office
    // For now it's intentionally minimal — main UI is in React
  }
}

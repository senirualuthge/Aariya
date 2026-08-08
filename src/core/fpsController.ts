// src/core/fpsController.ts
export enum FPSMode {
  Auto = 'auto',
  Force60 = 'force60',
  Force120 = 'force120',
}

export interface FPSControllerConfig {
  mode: FPSMode;
  monitorHz: number;
  currentTarget: number;
}

class FPSController {
  private userMode: FPSMode = FPSMode.Auto;
  private monitorHz: number = 60;
  private currentTarget: number = 60;
  
  private downgradeTimer: number = 0;
  private upgradeTimer: number = 0;
  private thermalTimer: number = 0;
  private thermalThrottling: boolean = false;
  
  // Thresholds
  private readonly DOWNGRADE_GPU_MS = 11.5; // ~87 FPS → drop from 120
  private readonly UPGRADE_GPU_MS = 7.5;    // ~133 FPS → allow 120
  private readonly DOWNGRADE_TIME_REQUIRED = 2.0; // seconds
  private readonly UPGRADE_TIME_REQUIRED = 5.0;   // seconds
  private readonly BACKGROUND_FPS = 30;
  
  // Frame timing tracking
  private frameTimings: number[] = [];
  private readonly FRAME_TIMING_BUFFER_SIZE = 120;
  
  constructor() {
    this.detectMonitorHz();
    this.setupFocusHandlers();
    this.loadUserPreferences();
  }
  
  private detectMonitorHz(): void {
    // Browser API for refresh rate (if available)
    if ('screen' in window && 'refreshRate' in (window.screen as any)) {
      this.monitorHz = (window.screen as any).refreshRate || 60;
    } else {
      // Fallback: assume 60Hz
      this.monitorHz = 60;
    }
    console.log(`[FPS Controller] Monitor refresh rate: ${this.monitorHz}Hz`);
  }
  
  private setupFocusHandlers(): void {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        this.setFPS(this.BACKGROUND_FPS);
        console.log('[FPS Controller] App unfocused, reducing to 30 FPS');
      } else {
        this.applyInitialCap();
        console.log('[FPS Controller] App focused, restoring FPS');
      }
    });
  }
  
  private loadUserPreferences(): void {
    const saved = localStorage.getItem('fpsMode');
    if (saved && Object.values(FPSMode).includes(saved as FPSMode)) {
      this.userMode = saved as FPSMode;
    }
  }
  
  async start(): Promise<void> {
    await this.applyInitialCap();
  }
  
  private async applyInitialCap(): Promise<void> {
    if (document.hidden) {
      this.setFPS(this.BACKGROUND_FPS);
      return;
    }
    
    switch (this.userMode) {
      case FPSMode.Force60:
        this.setFPS(60);
        break;
        
      case FPSMode.Force120:
        await this.trySet120();
        break;
        
      case FPSMode.Auto:
        if (this.monitorHz >= 120) {
          await this.trySet120();
        } else {
          this.setFPS(60);
        }
        break;
    }
  }
  
  private async trySet120(): Promise<void> {
    if (this.monitorHz < 120) {
      this.setFPS(60);
      return;
    }
    
    // Run performance test
    const canHandle120 = await this.performanceTest();
    
    if (canHandle120) {
      this.setFPS(120);
    } else {
      this.setFPS(60);
      console.log('[FPS Controller] Performance test failed, staying at 60 FPS');
    }
  }
  
  private async performanceTest(): Promise<boolean> {
    console.log('[FPS Controller] Running performance test...');
    
    // Warmup
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    // Sample 120 frames
    let avgFrameTime = 0;
    const samples = 120;
    
    for (let i = 0; i < samples; i++) {
      const start = performance.now();
      await new Promise(resolve => requestAnimationFrame(resolve));
      avgFrameTime += performance.now() - start;
    }
    
    avgFrameTime /= samples;
    const avgFPS = 1000 / avgFrameTime;
    
    console.log(`[FPS Controller] Performance test: ${avgFPS.toFixed(1)} FPS (avg frame time: ${avgFrameTime.toFixed(2)}ms)`);
    
    // Need ≥110 FPS headroom for stable 120
    return avgFPS >= 110;
  }
  
  update(deltaTime: number, gpuMs: number): void {
    if (document.hidden) return;
    
    this.recordFrameTime(deltaTime * 1000); // Convert to ms
    this.detectThermals(gpuMs);
    this.handleThermalPolicy();
    
    if (this.currentTarget === 120) {
      this.checkDowngrade(gpuMs, deltaTime);
    } else if (this.currentTarget === 60) {
      this.checkUpgrade(gpuMs, deltaTime);
    }
    
    this.applyVRRCap();
  }
  
  private recordFrameTime(frameTimeMs: number): void {
    this.frameTimings.push(frameTimeMs);
    if (this.frameTimings.length > this.FRAME_TIMING_BUFFER_SIZE) {
      this.frameTimings.shift();
    }
  }
  
  private checkDowngrade(gpuMs: number, deltaTime: number): void {
    if (this.userMode === FPSMode.Force60) return;
    
    if (gpuMs > this.DOWNGRADE_GPU_MS) {
      this.downgradeTimer += deltaTime;
    } else {
      this.downgradeTimer = 0;
    }
    
    if (this.downgradeTimer >= this.DOWNGRADE_TIME_REQUIRED) {
      this.setFPS(60);
      this.downgradeTimer = 0;
      this.logFPSChange(120, 60, 'performance_downgrade', gpuMs);
    }
  }
  
  private checkUpgrade(gpuMs: number, deltaTime: number): void {
    if (this.userMode === FPSMode.Force60) return;
    if (this.monitorHz < 120) return;
    if (this.thermalThrottling) return;
    
    if (gpuMs < this.UPGRADE_GPU_MS) {
      this.upgradeTimer += deltaTime;
    } else {
      this.upgradeTimer = 0;
    }
    
    if (this.upgradeTimer >= this.UPGRADE_TIME_REQUIRED) {
      this.setFPS(120);
      this.upgradeTimer = 0;
      this.logFPSChange(60, 120, 'performance_upgrade', gpuMs);
    }
  }
  
  private detectThermals(gpuMs: number): void {
    if (this.currentTarget === 120 && gpuMs > 12) {
      this.thermalTimer += 0.016; // Approximate frame time
    } else {
      this.thermalTimer = Math.max(0, this.thermalTimer - 0.016);
    }
    
    this.thermalThrottling = this.thermalTimer > 20; // 20s sustained
  }
  
  private handleThermalPolicy(): void {
    if (!this.thermalThrottling) return;
    
    if (this.currentTarget === 120) {
      this.setFPS(60);
      this.logFPSChange(120, 60, 'thermal_throttle', this.thermalTimer);
    }
  }
  
  private applyVRRCap(): void {
    // VRR (G-Sync/FreeSync) optimization
    const vrrLikely = this.monitorHz >= 120;
    
    if (vrrLikely && this.userMode !== FPSMode.Force60 && this.currentTarget === 120) {
      // Cap slightly below max to prevent VSync ceiling
      // This is handled by the render loop, not here
    }
  }
  
  private setFPS(fps: number): void {
    if (this.currentTarget === fps) return;
    
    this.currentTarget = fps;
    console.log(`[FPS Controller] Target FPS set to: ${fps}`);
    
    // Emit event for other systems
    window.dispatchEvent(new CustomEvent('fpsTargetChanged', { 
      detail: { fps, mode: this.userMode } 
    }));
  }
  
  private logFPSChange(from: number, to: number, reason: string, metric: number): void {
    console.log(`[FPS Controller] FPS changed: ${from} → ${to} (reason: ${reason}, metric: ${metric.toFixed(2)})`);
    
    // Could send to analytics here
    window.dispatchEvent(new CustomEvent('fpsChanged', {
      detail: { from, to, reason, metric }
    }));
  }
  
  setUserMode(mode: FPSMode): void {
    this.userMode = mode;
    localStorage.setItem('fpsMode', mode);
    this.applyInitialCap();
    console.log(`[FPS Controller] User mode set to: ${mode}`);
  }
  
  getUserMode(): FPSMode {
    return this.userMode;
  }
  
  getCurrentTarget(): number {
    return this.currentTarget;
  }
  
  getMonitorHz(): number {
    return this.monitorHz;
  }
  
  getAverageFrameTime(): number {
    if (this.frameTimings.length === 0) return 0;
    const sum = this.frameTimings.reduce((a, b) => a + b, 0);
    return sum / this.frameTimings.length;
  }
  
  getFrameTimings(): number[] {
    return [...this.frameTimings];
  }
  
  isThermalThrottling(): boolean {
    return this.thermalThrottling;
  }
}

export const fpsController = new FPSController();

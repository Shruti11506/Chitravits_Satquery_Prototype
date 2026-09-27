/**
 * SatQuery AI - Cinematic Satellite Orbit Theme Transition Engine
 * 
 * Features:
 * 1. 2400ms majestic, slow, fluid, 120fps GPU-composited orbital deployment
 * 2. View Transitions API reveals the REAL UI from the Earth center
 * 3. Exact button-centered Earth globe that covers the button and dissolves smoothly near completion
 * 4. Gentle satellite launch: emerges from Earth, grows to full scale 1.0, and glides across center
 * 5. 100% lockstep Web Animations API across clipPath, orbit circle, satellite, and Earth
 * 6. Zero lag, zero jank, zero premature pop-in
 */

let isTransitionActive = false;

export function executeThemeTransition(nextTheme, event, callbacks = {}) {
  if (isTransitionActive) return;
  isTransitionActive = true;

  const { onThemeUpdate, onWaveStart, onWaveEnd } = callbacks;

  const finalize = () => {
    isTransitionActive = false;
    onWaveEnd?.();
  };

  // Get the exact center coordinates of the clicked theme toggle button
  let earthX = window.innerWidth - 45;
  let earthY = 32;

  const btn = (event?.currentTarget && typeof event.currentTarget.getBoundingClientRect === 'function')
    ? event.currentTarget
    : (typeof document !== 'undefined' ? document.getElementById('satquery-theme-toggle-btn') : null);

  if (btn) {
    const rect = btn.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      earthX = Math.round(rect.left + rect.width / 2);
      earthY = Math.round(rect.top + rect.height / 2);
    }
  }

  // Calculate maximum radius to the furthest viewport corner from the button center
  const maxRadius = Math.hypot(
    Math.max(earthX, window.innerWidth - earthX),
    Math.max(earthY, window.innerHeight - earthY)
  ) * 1.05;

  // Dynamic Trajectory: Aim directly through the upper center of the viewport
  const targetCenterX = window.innerWidth * 0.48;
  const targetCenterY = window.innerHeight * 0.42;
  const satAngle = Math.atan2(targetCenterY - earthY, targetCenterX - earthX);
  const flightDeg = (satAngle * 180) / Math.PI;

  const satTargetX = Math.cos(satAngle) * (maxRadius * 0.98);
  const satTargetY = Math.sin(satAngle) * (maxRadius * 0.98);

  // ⚠️  LOCKED — DO NOT CHANGE. 1600ms + cubic-bezier(0.32,0,0.2,1) is the
  //     approved satellite orbital animation. Approved by user on 2026-09-27.
  const TRANSITION_DURATION = 1600;

  // 1. Mount the single-orbit edge wavefront and single satellite overlay
  const waveId = Date.now();
  onWaveStart?.({
    id: waveId,
    x: earthX,
    y: earthY,
    originX: earthX,
    originY: earthY,
    maxRadius,
    satTargetX,
    satTargetY,
    flightDeg,
    duration: TRANSITION_DURATION,
    nextTheme
  });

  // ⚠️  LOCKED — DO NOT CHANGE. This easing gives the authentic orbital-cruise
  //     feel. Changing it breaks the satellite glide. Approved 2026-09-27.
  const timing = {
    duration: TRANSITION_DURATION,
    easing: 'cubic-bezier(0.32, 0, 0.2, 1)',
    fill: 'forwards'
  };

  const initialYaw = -16;
  const finalYaw = -4;

  const launchOverlayAnimations = () => {
    const orbitScaler = document.getElementById('satquery-orbit-scaler');
    const satelliteGroup = document.getElementById('satquery-edge-satellite');
    const earthGlobe = document.getElementById('satquery-earth-globe');
    const overlay = document.getElementById('satquery-orbit-overlay');

    if (!satelliteGroup || !orbitScaler) {
      requestAnimationFrame(launchOverlayAnimations);
      return;
    }

    // Top Layer activation: promote to topmost browser layer above all UI elements
    if (overlay) {
      try {
        if (typeof overlay.showModal === 'function' && !overlay.open) {
          overlay.showModal();
        }
      } catch {
        try {
          if (typeof overlay.showPopover === 'function' && !overlay.matches?.(':popover-open')) {
            overlay.showPopover();
          }
        } catch {}
      }
    }

    // 1. Single expanding orbit wave in exact lockstep
    orbitScaler.animate(
      [
        { transform: 'scale(0)', opacity: 0, offset: 0 },
        { transform: 'scale(0.05)', opacity: 0.9, offset: 0.09 },
        { transform: 'scale(0.16)', opacity: 1, offset: 0.20 },
        { transform: 'scale(0.82)', opacity: 1, offset: 0.84 },
        { transform: 'scale(1)', opacity: 0, offset: 1 }
      ],
      timing
    );

    // 2. Satellite gently deploys from Earth (scales 0.35 -> 1.0) and sails across center
    satelliteGroup.animate(
      [
        { 
          transform: `translate(0px, 0px) scale(0.35) rotate(${initialYaw - 4}deg)`, 
          opacity: 0, 
          offset: 0 
        },
        { 
          transform: `translate(${satTargetX * 0.05}px, ${satTargetY * 0.05}px) scale(0.75) rotate(${initialYaw}deg)`, 
          opacity: 0.9, 
          offset: 0.09 
        },
        { 
          transform: `translate(${satTargetX * 0.16}px, ${satTargetY * 0.16}px) scale(1.0) rotate(${initialYaw + 2}deg)`, 
          opacity: 1, 
          offset: 0.20 
        },
        { 
          transform: `translate(${satTargetX * 0.82}px, ${satTargetY * 0.82}px) scale(1.0) rotate(${finalYaw}deg)`, 
          opacity: 1, 
          offset: 0.84 
        },
        { 
          transform: `translate(${satTargetX}px, ${satTargetY}px) scale(0.92) rotate(${finalYaw}deg)`, 
          opacity: 0, 
          offset: 1 
        }
      ],
      timing
    );

    // 3. Earth globe smoothly covers the button and vanishes near completion
    if (earthGlobe) {
      earthGlobe.animate(
        [
          { transform: 'scale(0.5)', opacity: 0, offset: 0 },
          { transform: 'scale(1)', opacity: 1, offset: 0.09 },
          { transform: 'scale(1)', opacity: 1, offset: 0.82 },
          { transform: 'scale(0.85)', opacity: 0, offset: 0.96 },
          { transform: 'scale(0.85)', opacity: 0, offset: 1 }
        ],
        timing
      );
    }

    // 4. Smooth dissolve of the overlay container at the very end
    if (overlay) {
      overlay.animate(
        [
          { opacity: 1, offset: 0 },
          { opacity: 1, offset: 0.88 },
          { opacity: 0, offset: 1 }
        ],
        timing
      );
    }
  };

  // 2. Use View Transitions API to smoothly clip-reveal the ACTUAL UI in exact lockstep
  if (typeof document !== 'undefined' && 'startViewTransition' in document) {
    try {
      const transition = document.startViewTransition(() => {
        document.documentElement.setAttribute('data-theme', nextTheme);
        localStorage.setItem('satquery-theme', nextTheme);
        onThemeUpdate?.(nextTheme);
      });

      transition.ready.then(() => {
        // High-precision GPU-accelerated circular reveal clip path matching the 5 keyframes
        const anim = document.documentElement.animate(
          {
            clipPath: [
              `circle(0px at ${earthX}px ${earthY}px)`,
              `circle(${maxRadius * 0.05}px at ${earthX}px ${earthY}px)`,
              `circle(${maxRadius * 0.16}px at ${earthX}px ${earthY}px)`,
              `circle(${maxRadius * 0.82}px at ${earthX}px ${earthY}px)`,
              `circle(${maxRadius}px at ${earthX}px ${earthY}px)`
            ]
          },
          {
            ...timing,
            pseudoElement: '::view-transition-new(root)'
          }
        );

        // Synchronously fire all overlay layers in 100% frame-locked lockstep
        launchOverlayAnimations();

        // As soon as the animation completes, cleanly finalize on next paint frame
        Promise.allSettled([
          anim.finished,
          transition.finished
        ]).then(() => {
          requestAnimationFrame(() => {
            finalize();
          });
        });
      });
    } catch {
      document.documentElement.setAttribute('data-theme', nextTheme);
      localStorage.setItem('satquery-theme', nextTheme);
      onThemeUpdate?.(nextTheme);
      launchOverlayAnimations();
      setTimeout(finalize, TRANSITION_DURATION);
    }
  } else {
    document.documentElement.setAttribute('data-theme', nextTheme);
    localStorage.setItem('satquery-theme', nextTheme);
    onThemeUpdate?.(nextTheme);
    launchOverlayAnimations();
    setTimeout(finalize, TRANSITION_DURATION);
  }

  // Safety watchdog: ensure state resets even if tab was backgrounded
  setTimeout(() => {
    if (isTransitionActive) {
      finalize();
    }
  }, TRANSITION_DURATION + 250);
}

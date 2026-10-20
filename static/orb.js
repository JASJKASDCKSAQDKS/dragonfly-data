/* ==========================================================================
   Seline — Aurora Particle Sphere + Nebula (Three.js)
   Fine-grained particle sphere in the #B993D6 → #8CA6DB aurora gradient:
   swirling dust shell, orbital rings, soft glowing core. No starfield.
   Exposes: window.SelineOrb = { setBrightness(0..1), setState(name) }
   ========================================================================== */

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';

const BG = '#0E0F13';

// Aurora gradient palette (sphere)
const AURORA_HOT = new THREE.Color('#f4eefc');
const AURORA_MID = new THREE.Color('#B993D6');
const AURORA_DEEP = new THREE.Color('#8CA6DB');

// ---------------------------------------------------------------------------
// Renderer / Scene / Camera
// ---------------------------------------------------------------------------
const canvas = document.getElementById('orb-canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setClearColor(BG, 1);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 0, 8);

// ---------------------------------------------------------------------------
// Shared uniforms
// ---------------------------------------------------------------------------
const shared = {
  uTime: { value: 0 },
  uVoiceBright: { value: 0 },   // 0..1, driven from audio amplitude
  uAgitation: { value: 0.15 },  // swirl speed — raised while thinking/speaking
};

// ---------------------------------------------------------------------------
// Nebula backdrop — FBM noise in aurora purple/blue, kept very subtle
// ---------------------------------------------------------------------------
const nebulaMat = new THREE.ShaderMaterial({
  depthWrite: false,
  uniforms: {
    uTime: shared.uTime,
    uAspect: { value: window.innerWidth / window.innerHeight },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */`
    varying vec2 vUv;
    uniform float uTime;
    uniform float uAspect;

    float hash(vec2 p) {
      return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
    }
    float noise(vec2 p) {
      vec2 i = floor(p);
      vec2 f = fract(p);
      vec2 u = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
                 mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
    }
    float fbm(vec2 p) {
      float v = 0.0;
      float a = 0.5;
      for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = p * 2.03 + vec2(11.3, 7.9);
        a *= 0.5;
      }
      return v;
    }

    void main() {
      vec2 uv = (vUv - 0.5) * vec2(uAspect, 1.0) * 2.4;
      float t = uTime * 0.014;

      float n1 = fbm(uv * 1.1 + vec2(t, -t * 0.6));
      float n2 = fbm(uv * 1.6 + vec2(-t * 0.7, t * 0.5) + n1);

      vec3 purple = vec3(0.725, 0.576, 0.839);   // #B993D6
      vec3 blue   = vec3(0.549, 0.651, 0.859);   // #8CA6DB

      vec3 col = vec3(0.0);
      col += purple * smoothstep(0.50, 0.95, n1) * 0.13;
      col += blue   * smoothstep(0.55, 1.00, n2) * 0.11;

      float vignette = 1.0 - smoothstep(0.35, 1.45, length(uv));
      col *= vignette;

      gl_FragColor = vec4(col, 1.0);
    }
  `,
});
const nebula = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), nebulaMat);
nebula.position.z = -14;
scene.add(nebula);

// ---------------------------------------------------------------------------
// Particle systems — shared aurora dust shader
// ---------------------------------------------------------------------------
const dustUniforms = {
  uTime: shared.uTime,
  uVoiceBright: shared.uVoiceBright,
  uAgitation: shared.uAgitation,
  uHot: { value: AURORA_HOT },
  uMid: { value: AURORA_MID },
  uDeep: { value: AURORA_DEEP },
};

const dustVertex = /* glsl */`
  attribute float aPhase;
  attribute float aSpeed;
  attribute float aSize;
  attribute float aHeat;
  uniform float uTime;
  uniform float uVoiceBright;
  uniform float uAgitation;
  varying float vFlicker;
  varying float vHeat;
  void main() {
    vec3 p = position;
    float ang = uTime * aSpeed * (0.3 + uAgitation * 1.1);
    float c = cos(ang);
    float s = sin(ang);
    p.xz = mat2(c, -s, s, c) * p.xz;
    float breathe = sin(uTime * 0.9 + aPhase * 6.2831) * (0.04 + uVoiceBright * 0.12);
    p *= 1.0 + breathe;
    vFlicker = 0.6 + 0.4 * sin(uTime * (1.5 + aSpeed * 2.5) + aPhase * 12.0);
    vHeat = aHeat;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = aSize * (1.0 + uVoiceBright * 1.1) * (150.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const dustFragment = /* glsl */`
  uniform vec3 uHot;
  uniform vec3 uMid;
  uniform vec3 uDeep;
  uniform float uVoiceBright;
  varying float vFlicker;
  varying float vHeat;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float alpha = smoothstep(0.5, 0.06, d);
    vec3 col = mix(uDeep, uMid, vHeat);
    col = mix(col, uHot, smoothstep(0.68, 1.0, vHeat));
    float glow = 0.65 + vFlicker * 0.75 + uVoiceBright * 0.8;
    gl_FragColor = vec4(col * glow, alpha * vFlicker);
  }
`;

function makeDustMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: dustUniforms,
    vertexShader: dustVertex,
    fragmentShader: dustFragment,
  });
}

function buildParticles({ count, radiusFn, sizeMin, sizeMax, speedMin, speedMax }) {
  const geo = new THREE.BufferGeometry();
  const positions = new Float32Array(count * 3);
  const phases = new Float32Array(count);
  const speeds = new Float32Array(count);
  const sizes = new Float32Array(count);
  const heats = new Float32Array(count);

  for (let i = 0; i < count; i++) {
    const p = radiusFn(i, count);
    positions[i * 3] = p[0];
    positions[i * 3 + 1] = p[1];
    positions[i * 3 + 2] = p[2];
    phases[i] = Math.random();
    speeds[i] = speedMin + Math.random() * (speedMax - speedMin);
    sizes[i] = sizeMin + Math.random() * (sizeMax - sizeMin);
    const r = Math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2]);
    heats[i] = THREE.MathUtils.clamp(1.35 - r * 0.55, 0, 1) * (0.7 + Math.random() * 0.3);
  }

  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
  geo.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1));
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
  geo.setAttribute('aHeat', new THREE.BufferAttribute(heats, 1));
  return geo;
}

// Dense dust shell — fibonacci sphere with radial jitter, fine grain
function fibonacciShell(i, count) {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (i / (count - 1)) * 2;
  const rad = Math.sqrt(1 - y * y);
  const theta = golden * i;
  const r = 1.45 + (Math.random() - 0.5) * 0.7;
  return [Math.cos(theta) * rad * r, y * r, Math.sin(theta) * rad * r];
}
const shell = new THREE.Points(
  buildParticles({
    count: 8000,
    radiusFn: fibonacciShell,
    sizeMin: 0.25, sizeMax: 0.85,
    speedMin: 0.05, speedMax: 0.35,
  }),
  makeDustMaterial()
);
scene.add(shell);

// Inner layer — tighter, brighter, faster
const inner = new THREE.Points(
  buildParticles({
    count: 2400,
    radiusFn: (i, count) => {
      const p = fibonacciShell(i, count);
      const r = 0.62 + Math.random() * 0.35;
      const len = Math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2]) || 1;
      return [p[0] / len * r, p[1] / len * r, p[2] / len * r];
    },
    sizeMin: 0.3, sizeMax: 0.75,
    speedMin: 0.3, speedMax: 0.8,
  }),
  makeDustMaterial()
);
scene.add(inner);

// Two tilted orbital rings
function ringDist(radius) {
  return () => {
    const a = Math.random() * Math.PI * 2;
    const r = radius + (Math.random() - 0.5) * 0.16;
    return [Math.cos(a) * r, (Math.random() - 0.5) * 0.05, Math.sin(a) * r];
  };
}
const ring1 = new THREE.Points(
  buildParticles({ count: 1300, radiusFn: ringDist(2.15), sizeMin: 0.2, sizeMax: 0.55, speedMin: 0.25, speedMax: 0.5 }),
  makeDustMaterial()
);
ring1.rotation.x = 0.42;
ring1.rotation.z = 0.18;
scene.add(ring1);

const ring2 = new THREE.Points(
  buildParticles({ count: 1000, radiusFn: ringDist(2.65), sizeMin: 0.15, sizeMax: 0.45, speedMin: 0.15, speedMax: 0.4 }),
  makeDustMaterial()
);
ring2.rotation.x = -0.3;
ring2.rotation.z = -0.35;
scene.add(ring2);

// ---------------------------------------------------------------------------
// Soft glowing core + halo
// ---------------------------------------------------------------------------
const coreMat = new THREE.ShaderMaterial({
  transparent: true,
  uniforms: {
    uTime: shared.uTime,
    uVoiceBright: shared.uVoiceBright,
  },
  vertexShader: /* glsl */`
    varying vec3 vNormal;
    varying vec3 vViewDir;
    void main() {
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      vNormal = normalize(normalMatrix * normal);
      vViewDir = normalize(-mv.xyz);
      gl_Position = projectionMatrix * mv;
    }
  `,
  fragmentShader: /* glsl */`
    varying vec3 vNormal;
    varying vec3 vViewDir;
    uniform float uTime;
    uniform float uVoiceBright;
    void main() {
      float facing = clamp(dot(normalize(vNormal), normalize(vViewDir)), 0.0, 1.0);
      float fresnel = pow(1.0 - facing, 2.0);
      float pulse = 0.5 + 0.5 * sin(uTime * 1.5708);   // ~4s breathing
      float energy = 0.7 + pulse * 0.2 + uVoiceBright * 1.8;
      vec3 deep = vec3(0.49, 0.56, 0.82);    // #7d8fd0
      vec3 mid  = vec3(0.725, 0.576, 0.839); // #B993D6
      vec3 hot  = vec3(0.957, 0.933, 0.988); // #f4eefc
      vec3 col = mix(deep, mid, facing);
      col = mix(col, hot, pow(facing, 2.6));
      col *= energy;
      col += mid * fresnel * (0.9 + uVoiceBright);
      gl_FragColor = vec4(col, 0.97);
    }
  `,
});
const core = new THREE.Mesh(new THREE.SphereGeometry(0.5, 64, 64), coreMat);
scene.add(core);

function makeGlowTexture(stops) {
  const size = 256;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [offset, alpha] of stops) {
    g.addColorStop(offset, `rgba(255,255,255,${alpha})`);
  }
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const atmosphereMat = new THREE.SpriteMaterial({
  map: makeGlowTexture([[0, 0.5], [0.25, 0.2], [0.6, 0.05], [1, 0]]),
  color: AURORA_MID.clone(),
  transparent: true,
  blending: THREE.AdditiveBlending,
  depthWrite: false,
  opacity: 0.45,
});
const atmosphere = new THREE.Sprite(atmosphereMat);
atmosphere.scale.setScalar(6.5);
scene.add(atmosphere);

// ---------------------------------------------------------------------------
// Post-processing — bloom so the sphere truly glows
// ---------------------------------------------------------------------------
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(
  new THREE.Vector2(window.innerWidth, window.innerHeight),
  1.25,   // strength
  0.9,    // radius
  0.1     // threshold
);
composer.addPass(bloom);

// ---------------------------------------------------------------------------
// External API — brightness + state
// ---------------------------------------------------------------------------
let brightnessTarget = 0;
let agitationTarget = 0.15;

const STATE_AGITATION = {
  idle: 0.15,
  listening: 0.45,
  thinking: 1.0,
  speaking: 0.6,
};

function setBrightness(v) {
  brightnessTarget = THREE.MathUtils.clamp(v || 0, 0, 1);
}

function setState(name) {
  agitationTarget = STATE_AGITATION[name] ?? 0.15;
}

window.SelineOrb = { setBrightness, setState };

// ---------------------------------------------------------------------------
// Subtle mouse parallax
// ---------------------------------------------------------------------------
const mouse = { x: 0, y: 0 };
window.addEventListener('pointermove', (e) => {
  mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
  mouse.y = (e.clientY / window.innerHeight) * 2 - 1;
});

// ---------------------------------------------------------------------------
// Resize + render loop
// ---------------------------------------------------------------------------
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
  nebulaMat.uniforms.uAspect.value = camera.aspect;
});

const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();
  shared.uTime.value = t;

  // Smoothly approach targets so nothing flickers or jumps.
  shared.uVoiceBright.value += (brightnessTarget - shared.uVoiceBright.value) * 0.18;
  shared.uAgitation.value += (agitationTarget - shared.uAgitation.value) * 0.04;

  // Slow global rotation + idle float.
  shell.rotation.y = t * 0.05;
  inner.rotation.y = -t * 0.07;
  const floatY = Math.sin(t * 0.6) * 0.07;
  core.position.y = floatY;
  shell.position.y = floatY;
  inner.position.y = floatY;
  ring1.position.y = floatY;
  ring2.position.y = floatY;
  atmosphere.position.y = floatY;

  atmosphereMat.opacity = 0.35 + shared.uVoiceBright.value * 0.55;
  bloom.strength = 1.15 + shared.uVoiceBright.value * 1.3;

  camera.position.x += (mouse.x * 0.35 - camera.position.x) * 0.03;
  camera.position.y += (-mouse.y * 0.25 - camera.position.y) * 0.03;
  camera.lookAt(0, 0, 0);

  composer.render();
}

animate();

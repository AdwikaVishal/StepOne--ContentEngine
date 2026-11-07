import { ArrowLeft, ArrowRight, ArrowUp, Film, Grid3X3, Image, Layers, LayoutGrid, Newspaper, PanelsTopLeft, Zap } from 'lucide-react'

export const LINKEDIN_LAYOUTS = [
  { id: 'magazine', name: 'Magazine', desc: '1 hero + 3 supporting', icon: Newspaper },
  { id: 'hero_right', name: 'Hero Right', desc: 'Hero right, thumbs left', icon: ArrowRight },
  { id: 'hero_left', name: 'Hero Left', desc: 'Hero left, thumbs right', icon: ArrowLeft },
  { id: 'hero_center', name: 'Hero Center', desc: 'Hero top, thumbs below', icon: ArrowUp },
  { id: 'panoramic', name: 'Panoramic', desc: 'Wide hero across top', icon: LayoutGrid },
  { id: 'bauhaus', name: 'Bauhaus', desc: 'Asymmetric geometric', icon: PanelsTopLeft },
  { id: 'minimal', name: 'Minimal Grid', desc: 'Clean 2x3 grid', icon: Grid3X3 },
]

export const STORY_LAYOUTS = [
  { id: 'single', name: 'Single', desc: 'Full-bleed image', min: 1, max: 1, icon: Image },
  { id: 'split_v', name: 'Split Vertical', desc: '2 side by side', min: 2, max: 2, icon: PanelsTopLeft },
  { id: 'split_h', name: 'Split Horizontal', desc: '2 top/bottom', min: 2, max: 2, icon: LayoutGrid },
  { id: 'grid_2x2', name: 'Grid 2x2', desc: '4 images grid', min: 4, max: 4, icon: Grid3X3 },
  { id: 'hero_bottom', name: 'Hero + Bottom', desc: '1 top, 2 bottom', min: 3, max: 3, icon: Layers },
  { id: 'polaroid', name: 'Polaroid Stack', desc: 'Angled stack', min: 2, max: 4, icon: Layers },
]

export const REEL_LAYOUTS = [
  { id: 'standard', name: 'Standard', desc: '30-60s highlight reel', icon: Film },
  { id: 'slideshow', name: 'Slideshow', desc: 'Images with transitions', icon: Image },
  { id: 'kinetic', name: 'Kinetic', desc: 'Dynamic motion text', icon: Zap },
]

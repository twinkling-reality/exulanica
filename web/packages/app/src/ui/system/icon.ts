/**
 * The interface's icons: one table from the names the interface uses to lucide glyphs (ISC
 * licence). No other module imports lucide (test/ui-system-icons.test.ts holds that), so changing
 * the look of an icon, or the whole set, is an edit to this table.
 *
 * Names say what the icon means here, not what it draws: `people`, not `users`. A surface asks for
 * a meaning and this table decides the picture.
 */
import {
  Armchair,
  ArrowLeft,
  Box,
  Camera,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  Clock,
  Coins,
  Compass,
  createElement,
  Ellipsis,
  Eye,
  Globe,
  Info,
  Keyboard,
  LibraryBig,
  LoaderCircle,
  Lock,
  LogIn,
  LogOut,
  Map,
  Menu,
  MessageCircle,
  Move,
  Palette,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Scale,
  Search,
  Settings,
  ShieldCheck,
  SkipForward,
  Sparkles,
  Store,
  Trash2,
  TriangleAlert,
  Undo2,
  UserRound,
  Users,
  X,
  type IconNode,
} from 'lucide';

const ICONS = {
  'add': Plus,
  'arrange': Move,
  'back': ArrowLeft,
  'busy': LoaderCircle,
  'cancelled': CircleX,
  'character': UserRound,
  'check': Check,
  'close': X,
  'clock': Clock,
  'companion': MessageCircle,
  'compare': Scale,
  'confirm': ShieldCheck,
  'design': Palette,
  'disclosure': ChevronDown,
  'explore': Compass,
  'failed': CircleAlert,
  'forward': ChevronRight,
  'info': Info,
  'keyboard': Keyboard,
  'leave': LogOut,
  'library': LibraryBig,
  'locked': Lock,
  'map': Map,
  'menu': Menu,
  'model': Sparkles,
  'more': Ellipsis,
  'next-minute': SkipForward,
  'object': Box,
  'pause': Pause,
  'people': Users,
  'photos': Camera,
  'place': Store,
  'play': Play,
  'ready': CircleCheck,
  'remove': Trash2,
  'reset': RotateCcw,
  'rest': Armchair,
  'search': Search,
  'settings': Settings,
  'sign-in': LogIn,
  'spends': Coins,
  'undo': Undo2,
  'view': Eye,
  'waiting': Clock,
  'warning': TriangleAlert,
  'world': Globe,
} as const satisfies Record<string, IconNode>;

export type IconName = keyof typeof ICONS;
export type IconSize = 'sm' | 'md' | 'lg';

export const ICON_NAMES = Object.freeze(Object.keys(ICONS) as IconName[]);

/** An icon as an inline SVG, hidden from assistive technology: its meaning is in the label beside it. */
export function icon(name: IconName, size: IconSize = 'md'): SVGElement {
  const svg = createElement(ICONS[name], {
    class: 'x-icon',
    'aria-hidden': 'true',
    focusable: 'false',
  });
  svg.setAttribute('data-size', size);
  svg.setAttribute('data-icon', name);
  return svg;
}

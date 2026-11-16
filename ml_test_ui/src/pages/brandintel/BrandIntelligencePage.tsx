/**
 * Brand Intelligence Studio — standalone workspace (Phase 1 + Phase 2).
 *
 * Separate from the Content Engine Studio: this workspace is an image-driven
 * brand identification product (Brand Library → Dataset Upload → Detection →
 * Review → Explorer → Export). Phase 1 ships the Brand Library tab, Phase 2
 * ships Dataset Upload; the remaining tabs are honest placeholders that
 * describe what each phase will deliver — no mock data, no fake results.
 */
import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Boxes, Database, Download, FolderSearch, ScanSearch, ShieldCheck, Sparkles,
} from 'lucide-react'
import { BrandProfilesPage } from '../BrandProfilesPage'
import { DatasetsPanel } from './DatasetsPanel'
import './BrandIntelligence.css'

type TabId = 'library' | 'upload' | 'detect' | 'review' | 'explorer' | 'export'

const TABS: {
  id: TabId
  label: string
  icon: typeof Boxes
  phase?: number
  title: string
  description: string
  bullets: string[]
}[] = [
  {
    id: 'library', label: 'Brand Library', icon: Boxes,
    title: 'Brand Library',
    description: 'Create brands and upload their visual identification references.',
    bullets: [],
  },
  {
    id: 'upload', label: 'Dataset Upload', icon: Database,
    title: 'Dataset Upload',
    description: 'Upload mixed, unlabelled image datasets — individual files, selections or ZIP archives — with validation, hashing, duplicate detection and immutable storage.',
    bullets: [
      'Chunked uploads with progress — the browser never holds the whole dataset',
      'ZIP archives with path-traversal and zip-bomb protection',
      'Content-addressed storage: originals are copied, never moved or modified',
    ],
  },
  {
    id: 'detect', label: 'Detection Studio', icon: ScanSearch, phase: 3,
    title: 'Detection Studio',
    description: 'Run the local brand recognition pipeline: OCR, logo-region matching and CLIP/DINOv2 visual similarity, fused into explainable multi-brand predictions.',
    bullets: [
      'Every signal runs locally — no external inference APIs',
      'Configurable, calibrated confidence thresholds per run',
      'Multi-brand detection: one photograph can belong to several brands',
    ],
  },
  {
    id: 'review', label: 'Review & Verification', icon: ShieldCheck, phase: 5,
    title: 'Review & Verification',
    description: 'Confirm, reject or reassign uncertain classifications. Human decisions are stored separately from raw model predictions — the original evidence is never overwritten.',
    bullets: [
      'Inspect OCR text, matched logos, similarity scores and regions',
      'Bulk actions with filters and a full decision history',
      'Model confidence, verification status and effective classification stay distinct',
    ],
  },
  {
    id: 'explorer', label: 'Dataset Explorer', icon: FolderSearch, phase: 6,
    title: 'Dataset Explorer',
    description: 'Browse brand-separated collections with confidence, OCR evidence, source filenames and verification status.',
    bullets: [
      'Per-brand galleries plus Multi-brand, Uncertain and Unmatched collections',
      'Search by filename, OCR text and brand',
      'Dataset statistics derived from predictions and decisions',
    ],
  },
  {
    id: 'export', label: 'Export Center', icon: Download, phase: 6,
    title: 'Export Center',
    description: 'Download separated datasets and full classification reports — traceable back to every original source image.',
    bullets: [
      'ZIP export per brand or all collections, original filenames preserved',
      'CSV / JSON classification, OCR and uncertain/unmatched reports',
      'Non-destructive: exports are copies, source files stay untouched',
    ],
  },
]

export function BrandIntelligencePage() {
  const [tab, setTab] = useState<TabId>('library')
  const active = TABS.find(t => t.id === tab)!

  return (
    <div className="bi-page fade-in">
      {/* ── Workspace header + tab strip ── */}
      <div className="bi-head">
        <div className="bi-head__title">
          <span className="bi-head__eyebrow">
            <Sparkles size={11} /> Brand Intelligence Studio
          </span>
          <p>Image-driven brand identification and dataset separation — fully local.</p>
        </div>
        <div className="bi-tabs" role="tablist" aria-label="Brand Intelligence sections">
          {TABS.map(item => {
            const Icon = item.icon
            const selected = tab === item.id
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={selected}
                className={`bi-tab${selected ? ' bi-tab--active' : ''}`}
                onClick={() => setTab(item.id)}
                title={item.phase ? `Arrives in Phase ${item.phase}` : undefined}
              >
                <Icon size={14} />
                <span>{item.label}</span>
                {item.phase ? <em className="bi-tab__phase">P{item.phase}</em> : null}
              </button>
            )
          })}
        </div>
      </div>

      {/* ── Tab content ── */}
      <motion.div
        key={tab}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
        className="bi-body"
      >
        {tab === 'library' ? (
          <BrandProfilesPage
            showReferencesTab
            title="Brand Library"
            subtitle="Create brands and upload reference photographs and logos for image-based brand identification."
          />
        ) : tab === 'upload' ? (
          <DatasetsPanel />
        ) : (
          <div className="bi-placeholder">
            <div className="bi-placeholder__icon" aria-hidden="true">
              <active.icon size={24} />
            </div>
            <h2>{active.title}</h2>
            <p>{active.description}</p>
            <ul>
              {active.bullets.map(b => <li key={b}>{b}</li>)}
            </ul>
            <span className="bi-placeholder__badge">
              {active.phase ? `Arrives in Phase ${active.phase}` : 'In development'}
            </span>
          </div>
        )}
      </motion.div>
    </div>
  )
}

export default BrandIntelligencePage

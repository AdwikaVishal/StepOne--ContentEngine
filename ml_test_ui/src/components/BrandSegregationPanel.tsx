import { Image, Layers, X, Sparkles } from 'lucide-react'
import { motion } from 'framer-motion'
import { AnimatedBtn } from './ui'

interface BrandSegregationPanelProps {
  brands: string[]
  selectedBrand: string
  renderFilesByBrand: File[][]
  onBrandsChange: (brands: string[]) => void
  onSelectedBrandChange: (brand: string) => void
  onRenderFilesChange: (index: number, files: File[]) => void
}

const BRAND_COUNT = 4
const BRAND_COLORS = ['#7c6aff', '#3b82f6', '#ec4899', '#10b981']

export default function BrandSegregationPanel({
  brands, selectedBrand, renderFilesByBrand,
  onBrandsChange, onSelectedBrandChange, onRenderFilesChange,
}: BrandSegregationPanelProps) {
  const cleanBrands = brands.map(b => b.trim()).filter(Boolean)
  const readyCount = brands.filter((brand, i) => brand.trim() && (renderFilesByBrand[i]?.length ?? 0) > 0).length

  const updateBrand = (index: number, value: string) => {
    const next = [...brands]; next[index] = value; onBrandsChange(next)
    if (selectedBrand && !next.map(b => b.trim()).includes(selectedBrand)) onSelectedBrandChange('')
  }

  return (
    <div className="brand-panel">
      {/* Header */}
      <div className="brand-panel__header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <div style={{ width: 28, height: 28, borderRadius: 8, background: 'var(--accent-subtle)', border: '1px solid var(--b-accent)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Layers size={14} color="var(--accent-light)" />
            </div>
            <h3 style={{ margin: 0 }}>Brand Segregation</h3>
          </div>
          <p>Define four brands, upload render/logo references, then choose the brand to prioritize in the generated output.</p>
        </div>
        <div className="brand-panel__status">
          <Sparkles size={12} />
          {readyCount}/{BRAND_COUNT} ready
        </div>
      </div>

      {/* Brand cards grid */}
      <div className="brand-panel__grid">
        {Array.from({ length: BRAND_COUNT }).map((_, index) => {
          const brand = brands[index] ?? ''
          const renderFiles = renderFilesByBrand[index] ?? []
          const color = BRAND_COLORS[index]
          const isReady = brand.trim() && renderFiles.length > 0

          return (
            <motion.div
              className="brand-card"
              key={index}
              style={{ borderColor: isReady ? `${color}35` : 'var(--b1)', background: isReady ? `${color}06` : 'var(--s3)' }}
              whileHover={{ borderColor: `${color}50` }}
              transition={{ duration: .15 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: isReady ? color : 'var(--b2)', boxShadow: isReady ? `0 0 6px ${color}` : 'none', transition: 'all .3s' }} />
                <label className="brand-card__label" htmlFor={`brand-${index}`} style={{ margin: 0 }}>Brand {index + 1}</label>
              </div>
              <input
                id={`brand-${index}`}
                className="brand-card__input"
                value={brand}
                onChange={e => updateBrand(index, e.target.value)}
                placeholder={`e.g. ${index === 0 ? 'HDFC Bank' : `Brand ${index + 1}`}`}
                style={{ borderColor: brand.trim() ? `${color}40` : 'var(--b1)' }}
              />

              <label className="brand-render-upload">
                <input type="file" accept="image/*" multiple onChange={e => onRenderFilesChange(index, Array.from(e.target.files ?? []))} />
                <Image size={13} />
                {renderFiles.length ? `${renderFiles.length} render image${renderFiles.length > 1 ? 's' : ''}` : 'Upload render/logo images'}
              </label>

              {renderFiles.length > 0 && (
                <div className="brand-render-list">
                  {renderFiles.slice(0, 3).map(file => (
                    <span key={file.name + file.size}>{file.name}</span>
                  ))}
                  {renderFiles.length > 3 && <span>+{renderFiles.length - 3} more</span>}
                  <button type="button" aria-label={`Clear render images for ${brand || `brand ${index + 1}`}`} onClick={() => onRenderFilesChange(index, [])}>
                    <X size={11} />
                  </button>
                </div>
              )}
            </motion.div>
          )
        })}
      </div>

      {/* Footer */}
      <div className="brand-panel__footer">
        <div className="brand-select">
          <label htmlFor="selected-brand">Content focus</label>
          <select
            id="selected-brand"
            value={selectedBrand}
            onChange={e => onSelectedBrandChange(e.target.value)}
            style={{ background: 'var(--s3)', border: '1px solid var(--b1)', color: 'var(--t1)', borderRadius: 10, outline: 'none' }}
          >
            <option value="">Select brand for content</option>
            {cleanBrands.map(brand => (
              <option key={brand} value={brand}>{brand}</option>
            ))}
          </select>
        </div>
        <AnimatedBtn
          type="button" size="sm" variant="ghost"
          label="Use GFF sample brands"
          onClick={() => { onBrandsChange(['HDFC Bank', 'NPCI', 'Razorpay', 'Paytm']); onSelectedBrandChange('HDFC Bank') }}
        >
          Use GFF sample brands
        </AnimatedBtn>
      </div>
    </div>
  )
}

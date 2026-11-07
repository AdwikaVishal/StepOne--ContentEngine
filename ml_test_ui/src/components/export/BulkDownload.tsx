/**
 * BulkDownload — all functionality preserved, premium visual upgrade.
 */
import { useState } from 'react'
import { Check, Package } from 'lucide-react'

import { motion } from 'framer-motion'
import { Spinner } from '../ui'

interface Props { files: Record<string, string> }

export default function BulkDownload({ files }: Props) {
  const [downloading, setDownloading] = useState(false)
  const [done, setDone] = useState(false)

  const downloadAll = async () => {
    setDownloading(true)
    const entries = Object.entries(files).filter(([n]) => /\.(jpg|jpeg|png|mp4|mov|md|json)$/i.test(n))
    for (const [name, url] of entries) {
      await new Promise<void>(resolve => {
        const a = document.createElement('a')
        a.href = url; a.download = name
        document.body.appendChild(a); a.click(); document.body.removeChild(a)
        setTimeout(resolve, 300)
      })
    }
    setDownloading(false); setDone(true)
    setTimeout(() => setDone(false), 3000)
  }

  const count = Object.keys(files).length

  return (
    <motion.button
      onClick={downloadAll}
      disabled={downloading || count === 0}
      whileHover={downloading || count === 0 ? {} : { scale: 1.02, y: -1 }}
      whileTap={downloading || count === 0 ? {} : { scale: 0.97 }}
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '9px 18px', borderRadius: 'var(--rs)',

        cursor: downloading ? 'wait' : count === 0 ? 'not-allowed' : 'pointer',

        background: done
          ? 'rgba(16,185,129,0.15)'
          : downloading
          ? 'var(--s3)'
          : 'linear-gradient(135deg,#7c6aff,#a78bfa)',
        color: downloading ? 'var(--t3)' : done ? 'var(--green)' : '#fff',
        fontSize: 13, fontWeight: 700,
        transition: 'all .2s',
        boxShadow: !downloading && !done && count > 0 ? '0 4px 16px rgba(124,106,255,0.3)' : 'none',
        border: done ? '1px solid rgba(16,185,129,0.3)' : 'none',
      }}
    >
      {downloading
        ? <Spinner size={14} color="#fff" />
        : done
        ? <Check size={14} />
        : <Package size={14} />
      }
      {downloading ? 'Downloading...' : done ? 'Downloaded!' : `Download All (${count})`}
    </motion.button>
  )
}

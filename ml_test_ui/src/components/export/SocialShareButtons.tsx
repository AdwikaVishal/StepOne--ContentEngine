/**
 * SocialShareButtons — all functionality preserved, premium visual upgrade.
 */
import { useState } from 'react'
import { Copy, Check, ExternalLink, Info, Share2 } from 'lucide-react'
import { motion } from 'framer-motion'

interface Props { platform: 'linkedin' | 'instagram' | 'stories' | 'reel'; caption: string }

export default function SocialShareButtons({ platform, caption }: Props) {
  const [copied, setCopied] = useState(false)

  const copyCaption = () => {
    navigator.clipboard.writeText(caption)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const shareLinkedIn = () => {
    const url = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(window.location.href)}&summary=${encodeURIComponent(caption.slice(0, 700))}`
    window.open(url, '_blank', 'width=600,height=500')
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
        <Share2 size={13} color="var(--t3)" />
        <span style={{ fontSize: 11, color: 'var(--t3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.07em' }}>Share</span>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <motion.button
          onClick={copyCaption}
          whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', background: copied ? 'rgba(16,185,129,0.1)' : 'var(--s3)',
            border: `1px solid ${copied ? 'rgba(16,185,129,0.3)' : 'var(--b1)'}`,
            borderRadius: 'var(--rs)', cursor: 'pointer', fontSize: 12,
            color: copied ? 'var(--green)' : 'var(--t2)', fontWeight: 600,
            transition: 'all .2s',
          }}
        >
          {copied ? <><Check size={12} /> Caption copied!</> : <><Copy size={12} /> Copy caption</>}
        </motion.button>

        {platform === 'linkedin' && (
          <motion.button
            onClick={shareLinkedIn}
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '8px 14px', background: 'rgba(10,102,194,0.15)',
              border: '1px solid rgba(10,102,194,0.3)',
              borderRadius: 'var(--rs)', cursor: 'pointer', fontSize: 12,
              color: '#60a5fa', fontWeight: 700,
            }}
          >
            <ExternalLink size={12} /> Share on LinkedIn
          </motion.button>
        )}

        {(platform === 'instagram' || platform === 'stories' || platform === 'reel') && (
          <div style={{ fontSize: 11, color: 'var(--t3)', display: 'flex', alignItems: 'center', gap: 5, padding: '8px 12px', background: 'var(--s3)', border: '1px solid var(--b1)', borderRadius: 'var(--rs)' }}>
            <Info size={12} /> Instagram requires the mobile app to post
          </div>
        )}
      </div>
    </div>
  )
}

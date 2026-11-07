import { useState, useEffect } from 'react'
import { Plus, Edit, Copy, Trash2, Save, X, Palette, Type, Users, Target } from 'lucide-react'
import { Card, AnimatedBtn, Spinner } from '../components/ui'
import { toast } from '../components/ui/Toast'
import { createBrandProfile, listBrandProfiles, updateBrandProfile, deleteBrandProfile, duplicateBrandProfile, uploadBrandAsset } from '../api'

export function BrandProfilesPage({ onBack }: { onBack?: () => void }) {
  const [profiles, setProfiles] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<any>(null)
  const [creating, setCreating] = useState(false)
  const [logoFile, setLogoFile] = useState<File | null>(null)
  const [referenceFiles, setReferenceFiles] = useState<File[]>([])
  
  useEffect(() => {
    loadProfiles()
  }, [])
  
  const loadProfiles = async () => {
    try {
      const res = await listBrandProfiles()
      setProfiles(res.profiles || [])
    } catch (e: any) {
      toast.error('Error', e.message)
    } finally {
      setLoading(false)
    }
  }
  
  const handleCreate = () => {
    setLogoFile(null)
    setReferenceFiles([])
    setCreating(true)
    setEditing({
      name: '',
      description: '',
      target_audience: '',
      campaign_objectives: '',
      tone_of_voice: 'professional',
      preferred_vocabulary: [],
      avoid_words_claims: [],
      preferred_cta: '',
      hashtag_guidance: '',
      brand_colors: [],
      fonts: [],
    })
  }
  
  const handleSave = async () => {
    if (!editing) return
    if (!editing.name?.trim()) { toast.error('Brand name required', 'Enter a name for this profile'); return }
    setLoading(true)
    try {
      let saved
      if (creating) {
        saved = await createBrandProfile(editing)
        toast.success('Created', 'Brand profile created')
      } else {
        saved = await updateBrandProfile(editing.id, editing)
        toast.success('Saved', 'Brand profile updated')
      }
      if (logoFile) saved = (await uploadBrandAsset(saved.id, logoFile, 'logo')).profile
      for (const file of referenceFiles) saved = (await uploadBrandAsset(saved.id, file, 'reference')).profile
      setEditing(null)
      setCreating(false)
      setLogoFile(null)
      setReferenceFiles([])
      loadProfiles()
    } catch (e: any) {
      toast.error('Error', e.message)
    } finally {
      setLoading(false)
    }
  }
  
  const handleDuplicate = async (id: string) => {
    try {
      await duplicateBrandProfile(id)
      toast.success('Duplicated', 'Brand profile duplicated')
      loadProfiles()
    } catch (e: any) {
      toast.error('Error', e.message)
    }
  }
  
  const handleDelete = async (id: string) => {
    if (!confirm('Delete this brand profile?')) return
    try {
      await deleteBrandProfile(id)
      toast.success('Deleted', 'Brand profile deleted')
      loadProfiles()
    } catch (e: any) {
      toast.error('Error', e.message)
    }
  }
  
  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 28, fontWeight: 800 }}>Brand Profiles</h1>
          <p style={{ color: 'var(--t3)', marginTop: 4 }}>Manage brand voice and guidelines</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {onBack && <AnimatedBtn onClick={onBack} variant="ghost">Back</AnimatedBtn>}
          <AnimatedBtn onClick={handleCreate} variant="default"><Plus size={16} /> New Profile</AnimatedBtn>
        </div>
      </div>
      
      {loading && !editing ? (
        <div style={{ textAlign: 'center', padding: 40 }}><Spinner size={24} /></div>
      ) : editing ? (
        <Card style={{ padding: 24 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 20 }}>{creating ? 'Create Profile' : 'Edit Profile'}</h2>
          
          <div style={{ display: 'grid', gap: 16 }}>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}>Brand Name *</label>
              <input value={editing.name || ''} onChange={e => setEditing({...editing, name: e.target.value})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} />
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}>Description</label>
              <textarea value={editing.description || ''} onChange={e => setEditing({...editing, description: e.target.value})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)', minHeight: 80 }} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}><Users size={12} style={{ display: 'inline' }} /> Target Audience</label>
                <input value={editing.target_audience || ''} onChange={e => setEditing({...editing, target_audience: e.target.value})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} />
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}><Target size={12} style={{ display: 'inline' }} /> Campaign Objectives</label>
                <input value={editing.campaign_objectives || ''} onChange={e => setEditing({...editing, campaign_objectives: e.target.value})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} />
              </div>
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}><Type size={12} style={{ display: 'inline' }} /> Tone of Voice</label>
              <select value={editing.tone_of_voice || 'professional'} onChange={e => setEditing({...editing, tone_of_voice: e.target.value})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }}>
                <option value="professional">Professional</option>
                <option value="casual">Casual</option>
                <option value="friendly">Friendly</option>
                <option value="bold">Bold</option>
                <option value="authentic">Authentic</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}>Preferred CTA</label>
              <input value={editing.preferred_cta || ''} onChange={e => setEditing({...editing, preferred_cta: e.target.value})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} placeholder="e.g., Learn more, Get started" />
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}>Hashtag Guidance</label>
              <input value={editing.hashtag_guidance || ''} onChange={e => setEditing({...editing, hashtag_guidance: e.target.value})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} placeholder="e.g., Use 3-5 relevant hashtags" />
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}>Preferred Vocabulary (comma separated)</label>
              <input value={(editing.preferred_vocabulary || []).join(', ')} onChange={e => setEditing({...editing, preferred_vocabulary: e.target.value.split(',').map((s:string)=>s.trim()).filter(Boolean)})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} placeholder="e.g., thoughtful, durable, community" />
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}>Words/Claims to Avoid (comma separated)</label>
              <input value={(editing.avoid_words_claims || []).join(', ')} onChange={e => setEditing({...editing, avoid_words_claims: e.target.value.split(',').map((s:string)=>s.trim()).filter(Boolean)})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} placeholder="e.g., best, #1, revolutionary" />
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}><Palette size={12} style={{ display: 'inline' }} /> Brand Colors</label>
              <input value={(editing.brand_colors || []).join(', ')} onChange={e => setEditing({...editing, brand_colors: e.target.value.split(',').map((s:string)=>s.trim()).filter(Boolean)})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} placeholder="#FF0000, #000000" />
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--t3)', display: 'block', marginBottom: 6 }}>Fonts (comma separated)</label>
              <input value={(editing.fonts || []).join(', ')} onChange={e => setEditing({...editing, fonts: e.target.value.split(',').map((s:string)=>s.trim()).filter(Boolean)})} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }} placeholder="e.g., Inter, Georgia" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <label style={{ fontSize: 12, color: 'var(--t3)' }}>Logo<input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={e => setLogoFile(e.target.files?.[0] || null)} style={{ display: 'block', marginTop: 8 }} /></label>
              <label style={{ fontSize: 12, color: 'var(--t3)' }}>Visual references<input type="file" multiple accept="image/png,image/jpeg,image/webp,image/svg+xml,application/pdf" onChange={e => setReferenceFiles(Array.from(e.target.files || []))} style={{ display: 'block', marginTop: 8 }} /></label>
            </div>
          </div>
          
          <div style={{ display: 'flex', gap: 8, marginTop: 24 }}>
            <AnimatedBtn onClick={handleSave} variant="default"><Save size={16} /> Save</AnimatedBtn>
            <AnimatedBtn onClick={() => { setEditing(null); setCreating(false); }} variant="ghost"><X size={16} /> Cancel</AnimatedBtn>
          </div>
        </Card>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {profiles.length === 0 ? (
            <Card style={{ padding: 40, textAlign: 'center' }}>
              <p style={{ color: 'var(--t3)' }}>No brand profiles yet</p>
              <AnimatedBtn onClick={handleCreate} variant="default" style={{ marginTop: 12 }}><Plus size={16} /> Create First Profile</AnimatedBtn>
            </Card>
          ) : profiles.map(profile => (
            <Card key={profile.id} style={{ padding: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <h3 style={{ fontSize: 16, fontWeight: 700 }}>{profile.name}</h3>
                  <p style={{ fontSize: 12, color: 'var(--t3)', marginTop: 2 }}>{profile.description || 'No description'}</p>
                  <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 10, padding: '2px 6px', background: 'var(--b2)', borderRadius: 4 }}>{profile.tone_of_voice}</span>
                    {profile.brand_colors?.slice(0,3).map((c:string) => (
                      <span key={c} style={{ width: 16, height: 16, borderRadius: '50%', background: c, border: '1px solid var(--b3)' }} />
                    ))}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <AnimatedBtn onClick={() => setEditing(profile)} variant="ghost" size="sm"><Edit size={14} /></AnimatedBtn>
                  <AnimatedBtn onClick={() => handleDuplicate(profile.id)} variant="ghost" size="sm"><Copy size={14} /></AnimatedBtn>
                  <AnimatedBtn onClick={() => handleDelete(profile.id)} variant="ghost" size="sm"><Trash2 size={14} /></AnimatedBtn>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

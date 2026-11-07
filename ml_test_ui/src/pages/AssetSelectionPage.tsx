import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles, Plus, Check, Zap, ChevronLeft, Star, LayoutGrid, Users,
  TrendingUp, Layout, Loader2, AlertCircle, Eye, RefreshCw,
  Mic, Store, Mic2, Handshake, Trophy, Tag, Search, Image as ImageIcon,
  SlidersHorizontal
} from 'lucide-react';

import { Card, Btn } from '../components/ui';
import { toast } from '../components/ui/Toast';
import { getEnhancedAssets, getJobStatus, getLayoutPreview } from '../api';
import { LINKEDIN_LAYOUTS, STORY_LAYOUTS, REEL_LAYOUTS } from '../constants/layouts';
import './AssetSelectionPage.css';

const categoryIcons = {
  stage: Mic,
  booth: Store,
  crowd: Users,
  speakers: Mic2,
  networking: Handshake,
  awards: Trophy,
};

// ---------- Layout Preview Component ----------
interface LayoutPreviewProps {
  layoutId: string;
  layoutType: 'linkedin' | 'story' | 'reel';
  selectedAssets: EnhancedAsset[];
  jobId?: string;
}

function LayoutPreview({ layoutId, layoutType, selectedAssets, jobId }: LayoutPreviewProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPreview = useCallback(async () => {
    if (!layoutId || selectedAssets.length === 0 || !jobId) {
      setPreviewUrl(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await getLayoutPreview({
        layout_type: layoutType,
        layout_id: layoutId,
        asset_ids: selectedAssets.map(a => a.id),
        job_id: jobId,
      });
      setPreviewUrl(result.preview_url);
    } catch (err) {
      console.error('Preview failed:', err);
      setError('Preview failed');
    } finally {
      setLoading(false);
    }
  }, [layoutId, layoutType, selectedAssets, jobId]);

  useEffect(() => {
    fetchPreview();
  }, [fetchPreview]);

  const aspectRatio = layoutType === 'linkedin' ? '1 / 1' : '9 / 16';

  return (
    <div className="layout-preview">
      <div className="layout-preview-header">
        <span>
          <Eye size={12} /> Live Preview
        </span>
        <button onClick={fetchPreview} disabled={loading} className="preview-refresh">
          <RefreshCw size={12} className={loading ? 'spin' : ''} />
        </button>
      </div>
      <div className="layout-preview-content" style={{ aspectRatio }}>
        {loading ? (
          <div className="preview-loading">
            <Loader2 size={20} className="spin" />
            <span>Generating...</span>
          </div>
        ) : error ? (
          <div className="preview-error">{error}</div>
        ) : previewUrl ? (
          <img src={previewUrl} alt="Layout preview" />
        ) : (
          <div className="preview-placeholder">Select assets to preview</div>
        )}
      </div>
    </div>
  );
}

// ---------- Main Component ----------
interface EnhancedAsset {
  id: string;
  url: string;
  score: number;
  faces: number;
  concepts: string[];
}

interface CategoryAssets {
  name: string;
  icon: string;
  color?: string;
  confidence?: number;
  assets: EnhancedAsset[];
}

interface JobProgressState {
  message?: string;
  percent?: number;
  status?: string;
}

interface Props {
  onContinue: (selectedAssetIds: string[], layouts: any) => void | Promise<void>;
  onBack: () => void;
  eventName: string;
  jobId?: string;
  files?: File[];
}

export default function AssetSelectionPage({
  onContinue,
  onBack,
  eventName,
  jobId,
  files = [],
}: Props) {
  // State
  const [isProcessing, setIsProcessing] = useState(true);
  const [jobProgress, setJobProgress] = useState<JobProgressState | null>(null);
  const [topAssets, setTopAssets] = useState<EnhancedAsset[]>([]);
  const [categories, setCategories] = useState<Record<string, CategoryAssets>>({});
  const [stats, setStats] = useState({ total: 0, unique: 0, deduped: 0 });
  const [tab, setTab] = useState<'overall' | 'categories'>('overall');
  const [activeCat, setActiveCat] = useState<string | null>(null);
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minScore, setMinScore] = useState(0);
  const [sortBy, setSortBy] = useState<'score' | 'faces' | 'name'>('score');
  const [searchQuery, setSearchQuery] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [liLayout, setLiLayout] = useState('hero_right');
  const [stLayout, setStLayout] = useState('single');
  const [rlLayout, setRlLayout] = useState('standard');

  const MAX_SELECTIONS = 10;
  const objectUrlsRef = useRef<string[]>([]);

  // Helper: revoke object URLs to prevent memory leaks
  const revokeObjectUrls = useCallback(() => {
    objectUrlsRef.current.forEach(url => URL.revokeObjectURL(url));
    objectUrlsRef.current = [];
  }, []);

  // Fallback category builder
  const buildFallbackCategories = useCallback((assets: EnhancedAsset[]) => {
    const definitions: Record<string, Omit<CategoryAssets, 'assets'> & { keywords: string[] }> = {
      stage:      { name: 'Stage',      icon: '🎤', color: '#e3f2fd', confidence: 0, keywords: ['stage', 'presentation', 'podium', 'speaker', 'keynote', 'talk'] },
      booth:      { name: 'Booth',      icon: '🏪', color: '#e8f5e9', confidence: 0, keywords: ['booth', 'exhibit', 'display', 'stand', 'kiosk', 'table'] },
      crowd:      { name: 'Crowd',      icon: '👥', color: '#fff3e0', confidence: 0, keywords: ['crowd', 'audience', 'people', 'attendees', 'gathering', 'event', 'conference'] },
      speakers:   { name: 'Speakers',   icon: '🎙️', color: '#f3e5f5', confidence: 0, keywords: ['speaker', 'presenter', 'host', 'moderator', 'panel'] },
      networking: { name: 'Networking', icon: '🤝', color: '#e0f7fa', confidence: 0, keywords: ['networking', 'conversation', 'handshake', 'meeting', 'chat'] },
      awards:     { name: 'Awards',     icon: '🏆', color: '#ffebee', confidence: 0, keywords: ['award', 'trophy', 'winner', 'prize', 'ceremony'] },
    };
    const generated: Record<string, CategoryAssets> = {};
    assets.forEach(asset => {
      const searchable = [asset.url, ...(asset.concepts ?? [])].join(' ').toLowerCase();
      for (const [id, definition] of Object.entries(definitions)) {
        if (definition.keywords.some(keyword => searchable.includes(keyword))) {
          generated[id] ??= {
            name: definition.name,
            icon: definition.icon,
            color: definition.color,
            confidence: 0,
            assets: [],
          };
          generated[id].assets.push(asset);
          break;
        }
      }
    });
    Object.values(generated).forEach(category => {
      const avgScore = category.assets.reduce((sum, a) => sum + a.score, 0) / category.assets.length;
      category.confidence = Math.round(Math.min(1, avgScore) * 100);
    });
    return generated;
  }, []);

  // Fallback when backend is unavailable
  const loadFallback = useCallback(() => {
    revokeObjectUrls();
    const seenHashes = new Set<string>();
    const newAssets: EnhancedAsset[] = [];
    files.forEach((file, i) => {
      const hash = `${file.name}-${file.size}`;
      if (seenHashes.has(hash)) return;
      seenHashes.add(hash);
      const url = URL.createObjectURL(file);
      objectUrlsRef.current.push(url);
      const nameConcepts = file.name.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
      newAssets.push({
        id: `asset-${i + 1}`,
        url,
        score: Math.floor(Math.random() * 25 + 75) / 100,
        faces: Math.floor(Math.random() * 5),
        concepts: Array.from(new Set(['event', 'conference', ...nameConcepts])).slice(0, 6),
      });
    });
    newAssets.sort((a, b) => b.score - a.score);
    const fallbackAssets = newAssets.slice(0, 10);
    setTopAssets(fallbackAssets);
    setCategories(buildFallbackCategories(fallbackAssets));
    setStats({
      total: files.length,
      unique: fallbackAssets.length,
      deduped: files.length - fallbackAssets.length,
    });
    setSelectedAssets(fallbackAssets.slice(0, 6).map(a => a.id));
    setIsProcessing(false);
    setError(null);
  }, [buildFallbackCategories, files, revokeObjectUrls]);

  // Fetch assets from backend
  const fetchAssets = useCallback(
    async (allowFallback = true) => {
      if (!jobId) {
        loadFallback();
        return true;
      }
      try {
        const data = await getEnhancedAssets(jobId);
        if (data.stats?.pending_processing && (!data.top_overall || data.top_overall.length === 0)) {
          setIsProcessing(true);
          setJobProgress(prev => prev ?? { message: 'Processing your assets...', percent: 0, status: 'processing' });
          return false;
        }
        if ((!data.top_overall || data.top_overall.length === 0) && files.length > 0 && allowFallback) {
          loadFallback();
          return true;
        }
        const top = data.top_overall || [];
        const generatedCategories = Object.values(data.per_category || {}).some(cat => cat.assets?.length > 0)
          ? data.per_category
          : buildFallbackCategories(top);
        setTopAssets(top);
        setCategories(generatedCategories || {});
        setStats({
          total: data.stats?.total ?? 0,
          unique: data.stats?.unique ?? top.length,
          deduped: data.stats?.deduped ?? data.stats?.duplicates_removed ?? 0,
        });
        setSelectedAssets(top.slice(0, 6).map(a => a.id));
        setIsProcessing(false);
        setError(null);
        return true;
      } catch (err: any) {
        const detail = err.response?.data?.detail || '';
        if (jobId && err.response?.status === 400 && detail.toLowerCase().includes('not completed')) {
          setIsProcessing(true);
          setJobProgress(prev => prev ?? { message: 'Processing your assets...', percent: 0, status: 'processing' });
          return false;
        }
        if (files.length > 0 && allowFallback) {
          toast.warning('Using local asset fallback', 'Enhanced asset scoring is not available yet.');
          loadFallback();
          return true;
        }
        setError('Failed to load assets. Please check the backend and try again.');
        setIsProcessing(false);
        return true;
      }
    },
    [buildFallbackCategories, files.length, jobId, loadFallback]
  );

  // Poll job status
  useEffect(() => {
    let cancelled = false;
    let pollInterval: number | undefined;

    const syncStatus = async () => {
      if (!jobId) return;
      try {
        const status = await getJobStatus(jobId);
        console.log("Poll response:", status);
        if (cancelled) return;
        const progress = status.progress;
        let percent = typeof progress?.pct === 'number' ? progress.pct : _toPct(status.status);
        
        if (['completed', 'SUCCESS'].includes(status.status)) {
          percent = 100;
        }
        
        setJobProgress({
          message: progress?.step || status.error || (status.status ? `Job ${status.status}` : undefined),
          percent,
          status: status.status,
        });
        if (['completed', 'SUCCESS'].includes(status.status)) {
          if (pollInterval) clearInterval(pollInterval);
          await fetchAssets(true);
        } else if (['failed', 'FAILURE'].includes(status.status)) {
          if (pollInterval) clearInterval(pollInterval);
          setError(status.error || 'Asset processing failed.');
          setIsProcessing(false);
        }
      } catch (err) {
        console.error('Job status poll failed:', err);
      }
    };

    fetchAssets(true).then(done => {
      if (cancelled || done || !jobId) return;
      syncStatus();
      pollInterval = window.setInterval(syncStatus, 2000);
    });

    return () => {
      cancelled = true;
      if (pollInterval) clearInterval(pollInterval);
      revokeObjectUrls();
    };
  }, [fetchAssets, jobId, revokeObjectUrls]);

  const progressPercent = jobProgress?.percent ?? (isProcessing ? 0 : 100);
  const currentMessage = jobProgress?.message || (jobProgress?.status ? `Job ${jobProgress.status}` : 'Processing your assets...');

  // Asset selection handlers
  const toggleAsset = useCallback(
    (assetId: string) => {
      setSelectedAssets(prev => {
        if (prev.includes(assetId)) return prev.filter(id => id !== assetId);
        if (prev.length < MAX_SELECTIONS) return [...prev, assetId];
        toast.warning(`You can select up to ${MAX_SELECTIONS} assets only.`);
        return prev;
      });
    },
    []
  );

  const handleGenerate = async () => {
    if (selectedAssets.length === 0) {
      toast.error('Please select at least one asset', 'You need to select at least one image to generate content.');
      return;
    }
    setGenerating(true);
    try {
      await onContinue(selectedAssets, { linkedin: liLayout, story: stLayout, reel: rlLayout });
      toast.success('Content generated!', `${eventName || 'Event'} content is ready!`);
    } catch (e) {
      console.error('Generation failed', e);
      toast.error('Generation failed', 'Please try again');
    } finally {
      setGenerating(false);
    }
  };

  // Derived data
  const categoryEntries = useMemo(
    () => Object.entries(categories).filter(([, cat]) => cat.assets.length > 0),
    [categories]
  );

  const baseDisplayAssets = tab === 'categories' && activeCat
    ? categories[activeCat]?.assets || []
    : topAssets;

  const displayAssets = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return [...baseDisplayAssets]
      .filter(a => a.score >= minScore)
      .filter(
        a =>
          !query ||
          a.url.toLowerCase().includes(query) ||
          a.concepts?.some(c => c.toLowerCase().includes(query))
      )
      .sort((a, b) => {
        if (sortBy === 'score') return b.score - a.score;
        if (sortBy === 'faces') return b.faces - a.faces;
        return a.url.localeCompare(b.url);
      });
  }, [baseDisplayAssets, minScore, searchQuery, sortBy]);

  const allKnownAssets = useMemo(() => {
    const byId = new Map<string, EnhancedAsset>();
    [...topAssets, ...Object.values(categories).flatMap(c => c.assets)].forEach(a => byId.set(a.id, a));
    return Array.from(byId.values());
  }, [categories, topAssets]);

  const selectedAssetList = selectedAssets
    .map(id => allKnownAssets.find(a => a.id === id))
    .filter(Boolean) as EnhancedAsset[];

  const selectTop = useCallback(
    (count: number) => {
      const topIds = [...displayAssets].sort((a, b) => b.score - a.score).slice(0, count).map(a => a.id);
      setSelectedAssets(topIds);
    },
    [displayAssets]
  );

  const selectAllDisplayed = useCallback(() => {
    const ids = displayAssets.slice(0, MAX_SELECTIONS).map(a => a.id);
    setSelectedAssets(ids);
  }, [displayAssets]);

  // Error state
  if (error) {
    return (
      <div className="error-state">
        <div className="error-icon">
          <AlertCircle size={32} />
        </div>
        <h2>Something went wrong</h2>
        <p>{error}</p>
        <div className="error-actions">
          <Btn onClick={onBack} variant="ghost">
            <ChevronLeft size={16} /> Back to Studio
          </Btn>
          <Btn onClick={() => window.location.reload()}>Retry</Btn>
        </div>
    </div>
  );
}

function _toPct(s?: string) {
  if (s === 'completed' || s === 'SUCCESS')  return 100
  if (s === 'PROGRESS')                      return 60
  if (s === 'running'  || s === 'STARTED')   return 30
  return 5
}

  return (
    <div className="asset-selection-page">
      {/* Header */}
      <div className="page-header">
        <motion.div initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }}>
          <h1>{isProcessing ? 'Processing Assets' : 'Curate Your Content'}</h1>
        </motion.div>
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}>
          {isProcessing
            ? 'AI is analyzing your uploaded media and selecting the best assets.'
            : `Choose your top ${MAX_SELECTIONS} images for final content generation.`}
        </motion.p>
        {!isProcessing && (stats.deduped > 0 || stats.unique > 0) && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 }}
            className="stats-badge"
          >
            <Sparkles size={13} />
            {stats.deduped > 0 && `${stats.deduped} duplicates removed · `}
            {stats.unique} unique assets
          </motion.div>
        )}
      </div>

      {/* Processing state */}
      <AnimatePresence>
        {isProcessing && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="processing-container">
            <div className="processing-header">
              <span>{currentMessage}</span>
              <span className="processing-percent">{Math.round(progressPercent)}%</span>
            </div>
            <div className="progress-bar">
              <motion.div
                className="progress-fill"
                animate={{ width: `${progressPercent}%` }}
                transition={{ width: { duration: 0.3 } }}
              />
              <motion.div
                className="progress-shimmer"
                animate={{ x: ['-100%', '100%'] }}
                transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main content (only when not processing) */}
      {!isProcessing && (
        <div className="main-grid">
          {/* LEFT COLUMN: Asset Gallery */}
          <div className="gallery-column">
            {/* Tabs */}
            <div className="tabs">
              <button
                className={`tab ${tab === 'overall' ? 'active' : ''}`}
                onClick={() => setTab('overall')}
              >
                <Star size={14} /> Top {topAssets.length} Overall
              </button>
              <button
                className={`tab ${tab === 'categories' ? 'active' : ''} ${categoryEntries.length === 0 ? 'disabled' : ''}`}
                onClick={() => categoryEntries.length > 0 && setTab('categories')}
                disabled={categoryEntries.length === 0}
              >
                <LayoutGrid size={14} /> By Category ({categoryEntries.length})
              </button>
            </div>

            {/* Filters Bar */}
            <Card className="filters-card">
              <div className="filters-row">
                <div className="filter-search">
                  <Search size={14} />
                  <input
                    type="text"
                    placeholder="Search by filename or concept..."
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                  />
                </div>
                <button className="filter-toggle" onClick={() => setShowFilters(!showFilters)}>
                  <SlidersHorizontal size={14} /> Filters
                </button>
              </div>

              <AnimatePresence>
                {showFilters && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="filter-options"
                  >
                    <div className="filter-group">
                      <label>Min Score: {Math.round(minScore * 100)}%</label>
                      <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.05}
                        value={minScore}
                        onChange={e => setMinScore(Number(e.target.value))}
                      />
                    </div>
                    <div className="filter-group">
                      <label>Sort by</label>
                      <select value={sortBy} onChange={e => setSortBy(e.target.value as any)}>
                        <option value="score">Score</option>
                        <option value="faces">Faces</option>
                        <option value="name">Name</option>
                      </select>
                    </div>
                    <div className="filter-actions">
                      <Btn variant="ghost" size="sm" onClick={() => selectTop(5)} disabled={displayAssets.length === 0}>
                        Select Top 5
                      </Btn>
                      <Btn variant="ghost" size="sm" onClick={selectAllDisplayed} disabled={displayAssets.length === 0}>
                        Select All
                      </Btn>
                      <Btn variant="ghost" size="sm" onClick={() => setSelectedAssets([])} disabled={selectedAssets.length === 0}>
                        Clear All
                      </Btn>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </Card>

            {/* Category Chips (only in categories tab) */}
            {tab === 'categories' && (
              <div className="category-chips">
                {categoryEntries.map(([id, cat]) => {
                  const Icon = categoryIcons[id as keyof typeof categoryIcons] ?? Tag;
                  return (
                    <motion.button
                      key={id}
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      className={`category-chip ${activeCat === id ? 'active' : ''}`}
                      onClick={() => setActiveCat(activeCat === id ? null : id)}
                    >
                      <Icon size={14} />
                      <span>{cat.name}</span>
                      <span className="chip-count">{cat.assets.length}</span>
                      <div className="chip-confidence">
                        <div className="confidence-bar" style={{ width: `${cat.confidence ?? 0}%` }} />
                      </div>
                    </motion.button>
                  );
                })}
              </div>
            )}

            {/* Asset Grid */}
            {topAssets.length === 0 ? (
              <Card className="empty-state">
                <ImageIcon size={44} />
                <h3>No Assets Found</h3>
                <p>Upload images or videos to see AI‑curated selections here.</p>
                <Btn onClick={onBack}>
                  <ChevronLeft size={16} /> Go to Upload
                </Btn>
              </Card>
            ) : displayAssets.length === 0 ? (
              <Card className="empty-state">
                <Search size={36} />
                <h3>No Matching Assets</h3>
                <p>Adjust the search text, category, or minimum score.</p>
                <Btn variant="ghost" onClick={() => { setSearchQuery(''); setMinScore(0); setActiveCat(null); }}>
                  Clear Filters
                </Btn>
              </Card>
            ) : (
              <div className="asset-grid">
                {displayAssets.map((asset, idx) => {
                  const isSelected = selectedAssets.includes(asset.id);
                  const isMaxReached = selectedAssets.length >= MAX_SELECTIONS && !isSelected;
                  return (
                    <motion.div
                      key={asset.id}
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: idx * 0.02 }}
                      className={`asset-card ${isSelected ? 'selected' : ''} ${isMaxReached ? 'max-reached' : ''}`}
                      onClick={() => !isMaxReached && toggleAsset(asset.id)}
                    >
                      <img src={asset.url} alt="" loading="lazy" />
                      <div className="asset-overlay">
                        <div className="select-indicator">
                          {isSelected ? <Check size={20} /> : <Plus size={20} />}
                        </div>
                      </div>
                      <div className="asset-badge score">
                        <TrendingUp size={10} /> {Math.round(asset.score * 100)}%
                      </div>
                      {asset.faces > 0 && (
                        <div className="asset-badge faces">
                          <Users size={9} /> {asset.faces}
                        </div>
                      )}
                      {isSelected && <motion.div className="selected-pulse" animate={{ opacity: [0.3, 0.6, 0.3] }} transition={{ duration: 2, repeat: Infinity }} />}
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>

          {/* RIGHT COLUMN: Layout Picker */}
          <div className="layouts-column">
            <Card className="layouts-card">
              <h3>
                <Layout size={18} /> Customize Layouts
              </h3>

              {[
                { label: 'LinkedIn', layouts: LINKEDIN_LAYOUTS, value: liLayout, setter: setLiLayout, type: 'linkedin' as const },
                { label: 'Instagram Stories', layouts: STORY_LAYOUTS, value: stLayout, setter: setStLayout, type: 'story' as const },
                { label: 'Instagram Reel', layouts: REEL_LAYOUTS, value: rlLayout, setter: setRlLayout, type: 'reel' as const },
              ].map(({ label, layouts, value, setter, type }) => (
                <div key={label} className="layout-group">
                  <div className="layout-group-label">{label}</div>
                  <div className="layout-options">
                    {layouts.map(l => {
                      const LayoutIcon = l.icon;
                      return (
                        <motion.button
                          key={l.id}
                          whileHover={{ scale: 1.01 }}
                          whileTap={{ scale: 0.99 }}
                          className={`layout-option ${value === l.id ? 'active' : ''}`}
                          onClick={() => setter(l.id)}
                        >
                          <LayoutIcon size={16} />
                          <div className="layout-info">
                            <div className="layout-name">{l.name}</div>
                            <div className="layout-desc">{l.desc}</div>
                          </div>
                          {value === l.id && <Check size={14} />}
                        </motion.button>
                      );
                    })}
                  </div>
                  <LayoutPreview layoutId={value} layoutType={type} selectedAssets={selectedAssetList} jobId={jobId} />
                </div>
              ))}
            </Card>
          </div>
        </div>
      )}

      {/* Floating Action Bar */}
      {!isProcessing && (
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.25 }}
          className="floating-bar"
        >
          <Card className="floating-card">
            <div className="selected-thumbnails">
              {selectedAssets.slice(0, 6).map(assetId => {
                const asset = allKnownAssets.find(a => a.id === assetId);
                return asset ? (
                  <div key={assetId} className="thumbnail">
                    <img src={asset.url} alt="" />
                  </div>
                ) : null;
              })}
              {selectedAssets.length > 6 && (
                <div className="thumbnail-more">+{selectedAssets.length - 6}</div>
              )}
              {selectedAssets.length === 0 && (
                <div className="placeholder-text">Select images to continue</div>
              )}
            </div>
            <div className={`selection-count ${selectedAssets.length === MAX_SELECTIONS ? 'max' : ''}`}>
              {selectedAssets.length}/{MAX_SELECTIONS}
            </div>
            <div className="floating-actions">
              <Btn variant="ghost" size="md" onClick={onBack}>
                <ChevronLeft size={15} /> Back
              </Btn>
              <motion.button
                className="generate-btn"
                onClick={handleGenerate}
                disabled={selectedAssets.length === 0 || generating}
                whileHover={selectedAssets.length > 0 && !generating ? { scale: 1.02, y: -1 } : {}}
                whileTap={selectedAssets.length > 0 && !generating ? { scale: 0.97 } : {}}
              >
                {generating ? <Loader2 size={16} className="spin" /> : <Zap size={16} />}
                {generating ? 'Generating...' : 'Generate Content'}
              </motion.button>
            </div>
          </Card>
        </motion.div>
      )}
    </div>
  );
}
const kind = window.RESULT_LIBRARY_KIND;
const search = document.getElementById('globalSearch');
const root = document.getElementById('globalResults');
const status = document.getElementById('libraryStatus');
let videos = [];

async function get(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Unable to load saved results (${response.status})`);
  return response.json();
}

function render() {
  const query = search.value.trim().toLowerCase();
  const matches = videos.filter(v =>
    [v.title, v.searchText].join(' ').toLowerCase().includes(query)
  );
  root.replaceChildren();
  status.textContent = matches.length
    ? `${matches.length} video(s) found`
    : 'No saved videos match your search.';

  for (const video of matches) {
    const card = document.createElement('article');
    card.className = 'document-card';
    const info = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = video.title;
    const detail = document.createElement('p');
    detail.className = 'muted';
    const count = kind === 'clips' ? video.count + ' saved clip(s)' : video.count + ' transcript section(s)';
    detail.textContent = count;
    info.append(title, detail);

    const actions = document.createElement('div');
    actions.className = 'button-row';
    const open = document.createElement('a');
    open.className = 'button-link secondary';
    open.href = `/videos/${encodeURIComponent(video.id)}/${kind === 'clips' ? 'clips' : 'transcript'}`;
    open.textContent = kind === 'clips' ? 'View clips' : 'View transcription';
    actions.append(open);
    card.append(info, actions);
    root.append(card);
  }
}

async function load() {
  try {
    const allVideos = await get('/api/videos');
    const results = await Promise.all(allVideos.map(async v => {
      try {
        if (kind === 'clips') {
          const data = await get(`/api/videos/${encodeURIComponent(v.id)}/clips`);
          const clips = data.clips || [];
          if (!clips.length) return null;
          return {id: v.id, title: v.title, count: clips.length,
            searchText: clips.map(c => `${c.title || ''} ${c.summary || ''}`).join(' ')};
        }
        const data = await get(`/api/videos/${encodeURIComponent(v.id)}`);
        const transcript = (data.steps || []).filter(s => s.kind === 'transcript');
        if (!transcript.length) return null;
        return {id: v.id, title: v.title, count: transcript.length,
          searchText: transcript.map(s => s.body || '').join(' ')};
      } catch (error) {
        console.warn('Unable to load results for video', v.id, error);
        return null;
      }
    }));
    videos = results.filter(Boolean);
    render();
  } catch (error) {
    status.textContent = error.message;
  }
}

search.addEventListener('input', render);
load();

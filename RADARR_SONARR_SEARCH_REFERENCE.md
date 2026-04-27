# Radarr/Sonarr Search UX & API Reference
## For BookOtter Per-Item Search Redesign

**Document Date**: April 2026  
**Radarr Version**: v6.1.1 (latest)  
**Sonarr Version**: v4.0.17 (latest)  
**Scope**: Search affordances, interactive search results table, per-row actions, API endpoints, rejection reasons, status badges

---

## 1. AUTOMATIC SEARCH vs INTERACTIVE SEARCH

### 1.1 Two Distinct Affordances

Both Radarr and Sonarr expose **two separate search buttons** on the item detail page (movie/series/episode):

#### **Automatic Search** (Quick Search)
- **UI Label**: "Search" button (magnifying glass icon) in Radarr; "Quick Search" button in Sonarr
- **Behavior**: Triggers a background command that searches all configured indexers and **automatically grabs the best match** according to quality profiles and custom formats
- **User Experience**: Fire-and-forget; no UI interaction required after clicking
- **When to use**: User trusts Radarr/Sonarr's decision-making and wants the fastest path to download
- **API Trigger**: `POST /api/v3/command` with command name `MovieSearch` (Radarr) or `EpisodeSearch` (Sonarr)

**Evidence** ([Radarr MovieSearchCell.tsx](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/frontend/src/Movie/MovieSearchCell.tsx#L36-L52)):
```typescript
const handleSearchPress = useCallback(() => {
  dispatch(
    executeCommand({
      name: MOVIE_SEARCH,
      movieIds: [movieId],
    })
  );
}, [movieId, dispatch]);

return (
  <TableRowCell className={styles.movieSearchCell}>
    <SpinnerIconButton
      name={icons.SEARCH}
      isSpinning={isSearching}
      title={translate('AutomaticSearch')}
      onPress={handleSearchPress}
    />
```

#### **Interactive Search** (Manual Search)
- **UI Label**: "Interactive Search" button (interactive icon) in both Radarr and Sonarr
- **Behavior**: Opens a modal/page showing **all candidate releases ranked by score**, allowing the user to manually pick which one to download
- **User Experience**: User reviews all options, sees rejection reasons, custom format scores, and can override quality/language/format settings before grabbing
- **When to use**: User wants control; automatic search didn't find anything; user wants to understand why a release was rejected
- **API Trigger**: `GET /api/v3/release?movieId={id}` (Radarr) or `GET /api/v3/release?episodeId={id}` (Sonarr)

**Evidence** ([Radarr MovieSearchCell.tsx](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/frontend/src/Movie/MovieSearchCell.tsx#L54-L64)):
```typescript
<IconButton
  name={icons.INTERACTIVE}
  title={translate('InteractiveSearch')}
  onPress={setInteractiveSearchModalOpen}
/>

<MovieInteractiveSearchModal
  isOpen={isInteractiveSearchModalOpen}
  movieId={movieId}
  onModalClose={setInteractiveSearchModalClosed}
/>
```

---

## 2. INTERACTIVE SEARCH RESULTS TABLE

### 2.1 Column Layout (Radarr & Sonarr)

The interactive search results are displayed as a **sortable, filterable table** with the following columns (in order):

| Column | Data Type | Purpose | Notes |
|--------|-----------|---------|-------|
| **Protocol** | Enum (Torrent/Usenet) | Download protocol | Shows icon (torrent/usenet) |
| **Age** | Integer (days) + decimals (hours/minutes) | Release age | Formatted as "1d 5h" or "12h 30m" |
| **Title** | String | Release name | Clickable link to indexer info URL |
| **Indexer** | String | Source indexer name | e.g., "The Pirate Bay", "NZBGeek" |
| **History** | Icon + Tooltip | Download history | Shows grabbed/failed/blocklisted status with timestamp |
| **Size** | Long (bytes) | Release file size | Formatted as "1.5 GB", "450 MB" |
| **Peers** | Integer (seeders/leechers) | Torrent peer count | Only shown for torrent protocol; shows "S: 50 / L: 10" |
| **Languages** | List<Language> | Audio/subtitle languages | Rendered as language badges |
| **Quality** | QualityModel | Video quality | e.g., "1080p Bluray", "720p HDTV" with revision |
| **Custom Format Score** | Integer | Custom format match score | Tooltip shows which formats matched |
| **Indexer Flags** | List<String> | Indexer-specific flags | Popover shows flags like "Freeleech", "Half-Leech" |
| **Rejections** | List<String> | Why release was rejected | Popover shows rejection reasons (see section 5) |
| **Download** | Action buttons | Grab or override | Two buttons: grab + override-and-grab |

**Evidence** ([Radarr InteractiveSearchRow.tsx](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/frontend/src/InteractiveSearch/InteractiveSearchRow.tsx#L194-L385)):
```typescript
return (
  <TableRow>
    <TableRowCell className={styles.protocol}>
      <ProtocolLabel protocol={protocol} />
    </TableRowCell>
    <TableRowCell className={styles.age} title={formatDateTime(...)}>
      {formatAge(age, ageHours, ageMinutes)}
    </TableRowCell>
    <TableRowCell>
      <Link to={infoUrl} title={title}>{title}</Link>
    </TableRowCell>
    <TableRowCell className={styles.indexer}>{indexer}</TableRowCell>
    <TableRowCell className={styles.history}>
      {/* History icons: grabbed, failed, blocklisted */}
    </TableRowCell>
    <TableRowCell className={styles.size}>{formatBytes(size)}</TableRowCell>
    <TableRowCell className={styles.peers}>
      {protocol === 'torrent' ? <Peers seeders={seeders} leechers={leechers} /> : null}
    </TableRowCell>
    <TableRowCell className={styles.languages}>
      <MovieLanguages languages={languages} />
    </TableRowCell>
    <TableRowCell className={styles.quality}>
      <MovieQuality quality={quality} showRevision={true} />
    </TableRowCell>
    <TableRowCell className={styles.customFormatScore}>
      <Tooltip anchor={formatCustomFormatScore(...)} tooltip={<MovieFormats formats={customFormats} />} />
    </TableRowCell>
    <TableRowCell className={styles.indexerFlags}>
      {indexerFlags.length ? <Popover anchor={<Icon name={icons.FLAG} />} body={...} /> : null}
    </TableRowCell>
    <TableRowCell className={styles.rejected}>
      {rejections.length ? <Popover anchor={<Icon name={icons.DANGER} />} body={...} /> : null}
    </TableRowCell>
    <TableRowCell className={styles.download}>
      {/* Download buttons */}
    </TableRowCell>
  </TableRow>
);
```

### 2.2 Sorting & Filtering

- **Sorting**: All columns are sortable by clicking the column header
- **Filtering**: A filter modal allows filtering by:
  - Protocol (Torrent/Usenet)
  - Indexer
  - Language
  - Quality
  - Custom format score range
  - Rejection status (approved/rejected/temporarily rejected)

---

## 3. PER-ROW ACTIONS

### 3.1 Download Actions

Each row in the interactive search results has **two download buttons**:

#### **Button 1: Grab (Default Download)**
- **Icon**: Download icon
- **Behavior**: 
  - If `downloadAllowed` is true: Immediately grabs the release
  - If `downloadAllowed` is false: Shows a confirmation modal asking user to confirm
- **Payload**: `{ guid, indexerId }`
- **API Endpoint**: `POST /api/v3/release` (Radarr/Sonarr)

**Evidence** ([Radarr InteractiveSearchRow.tsx](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/frontend/src/InteractiveSearch/InteractiveSearchRow.tsx#L153-L180)):
```typescript
const onGrabPressWrapper = useCallback(() => {
  if (downloadAllowed) {
    onGrabPress({
      guid,
      indexerId,
    });
    return;
  }
  setIsConfirmGrabModalOpen(true);
}, [guid, indexerId, downloadAllowed, onGrabPress, setIsConfirmGrabModalOpen]);

const onGrabConfirm = useCallback(() => {
  setIsConfirmGrabModalOpen(false);
  onGrabPress({
    guid,
    indexerId,
    ...searchPayload,
  });
}, [guid, indexerId, searchPayload, onGrabPress, setIsConfirmGrabModalOpen]);
```

#### **Button 2: Override and Grab**
- **Icon**: Overlaid interactive + download icons
- **Behavior**: Opens a modal allowing the user to **override quality, language, and custom format settings** before grabbing
- **Payload**: `{ guid, indexerId, movieId, quality, languages, shouldOverride: true }`
- **API Endpoint**: `POST /api/v3/release` with `shouldOverride: true` (Radarr/Sonarr)
- **Use Case**: User wants to grab a release that doesn't meet the normal quality cutoff, or wants to force a specific language/quality combo

**Evidence** ([Radarr InteractiveSearchRow.tsx](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/frontend/src/InteractiveSearch/InteractiveSearchRow.tsx#L341-L359)):
```typescript
<Link
  className={styles.manualDownloadContent}
  title={translate('OverrideAndAddToDownloadQueue')}
  onPress={onOverridePress}
>
  <div className={styles.manualDownloadContent}>
    <Icon className={styles.interactiveIcon} name={icons.INTERACTIVE} size={12} />
    <Icon className={styles.downloadIcon} name={icons.CIRCLE_DOWN} size={10} />
  </div>
</Link>

<OverrideMatchModal
  isOpen={isOverrideModalOpen}
  title={title}
  indexerId={indexerId}
  guid={guid}
  movieId={mappedMovieId}
  languages={languages}
  quality={quality}
  protocol={protocol}
  isGrabbing={isGrabbing}
  grabError={grabError}
  onModalClose={onOverrideModalClose}
/>
```

### 3.2 Blocklist Action (Implicit)

- **Trigger**: User can blocklist a release by clicking the blocklist icon in the History column
- **Behavior**: Adds the release to the blocklist and optionally triggers a new search for the next best match
- **API Endpoint**: `POST /api/v3/blocklist` (Radarr/Sonarr)
- **Note**: Not a direct per-row action button, but accessible via the History column popover

---

## 4. API ENDPOINTS

### 4.1 Automatic Search (Trigger)

**Endpoint**: `POST /api/v3/command`

**Request Body**:
```json
{
  "name": "MovieSearch",  // or "EpisodeSearch" for Sonarr
  "movieIds": [123],      // or "episodeIds": [456] for Sonarr
  "sendUpdatesToClient": true
}
```

**Response**: 
```json
{
  "id": 1,
  "name": "MovieSearch",
  "commandName": "MovieSearch",
  "body": { "movieIds": [123] },
  "priority": "normal",
  "status": "queued",
  "queued": "2026-04-27T10:30:00Z",
  "started": null,
  "ended": null,
  "duration": null,
  "exception": null,
  "trigger": "manual",
  "clientUserAgent": "Mozilla/5.0...",
  "sendUpdatesToClient": true,
  "suppressMessages": false
}
```

**Evidence** ([Radarr CommandController.cs](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/src/Radarr.Api.V3/Commands/CommandController.cs#L54-L79)):
```csharp
[RestPostById]
[Consumes("application/json")]
[Produces("application/json")]
public ActionResult<CommandResource> StartCommand([FromBody] CommandResource commandResource)
{
  var commandType = _knownTypes.GetImplementations(typeof(Command))
    .Single(c => c.Name.Replace("Command", "")
      .Equals(commandResource.Name, StringComparison.InvariantCultureIgnoreCase));
  
  var command = STJson.Deserialize(body, commandType) as Command;
  command.SuppressMessages = !command.SendUpdatesToClient;
  command.SendUpdatesToClient = true;
  
  var trackedCommand = _commandQueueManager.Push(command, priority, CommandTrigger.Manual);
  return Created(trackedCommand.Id);
}
```

---

### 4.2 Interactive Search (List Releases)

**Endpoint**: `GET /api/v3/release`

**Query Parameters**:
- `movieId={id}` (Radarr) or `episodeId={id}` (Sonarr) — required to fetch releases for a specific item
- Optional: `seriesId={id}&seasonNumber={num}` (Sonarr) for season-level search

**Response**: Array of ReleaseResource objects

```json
[
  {
    "guid": "abc123def456",
    "quality": {
      "quality": {
        "id": 3,
        "name": "1080p Bluray",
        "source": "bluray",
        "resolution": 1080
      },
      "revision": {
        "version": 1,
        "real": 0
      }
    },
    "customFormats": [
      {
        "id": 1,
        "name": "Remux",
        "includeCustomFormatWhenRenaming": false
      }
    ],
    "customFormatScore": 85,
    "age": 5,
    "ageHours": 120.5,
    "ageMinutes": 7230,
    "size": 1610612736,
    "indexerId": 1,
    "indexer": "The Pirate Bay",
    "releaseGroup": "GROUP",
    "title": "Movie.Title.2024.1080p.BluRay.x264-GROUP",
    "languages": [
      {
        "id": 1,
        "name": "English"
      }
    ],
    "mappedMovieId": 123,
    "approved": false,
    "temporarilyRejected": false,
    "rejected": true,
    "rejections": [
      "Quality cutoff not met",
      "Custom format score below threshold"
    ],
    "publishDate": "2026-04-22T10:30:00Z",
    "commentUrl": "https://example.com/comment",
    "downloadUrl": "https://example.com/download",
    "infoUrl": "https://example.com/info",
    "movieRequested": true,
    "downloadAllowed": false,
    "releaseWeight": 0,
    "seeders": 50,
    "leechers": 10,
    "protocol": "torrent",
    "indexerFlags": ["Freeleech", "Half-Leech"]
  }
]
```

**Evidence** ([Radarr ReleaseController.cs](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/src/Radarr.Api.V3/Indexers/ReleaseController.cs#L127-L157)):
```csharp
[HttpGet]
[Produces("application/json")]
public async Task<List<ReleaseResource>> GetReleases(int? movieId)
{
  if (movieId.HasValue)
  {
    return await GetMovieReleases(movieId.Value);
  }
  return await GetRss();
}

private async Task<List<ReleaseResource>> GetMovieReleases(int movieId)
{
  try
  {
    var decisions = await _releaseSearchService.MovieSearch(movieId, true, true);
    var prioritizedDecisions = _prioritizeDownloadDecision.PrioritizeDecisionsForMovies(decisions);
    return MapDecisions(prioritizedDecisions);
  }
  catch (SearchFailedException ex)
  {
    throw new NzbDroneClientException(HttpStatusCode.BadRequest, ex.Message);
  }
}
```

---

### 4.3 Grab Release (Download)

**Endpoint**: `POST /api/v3/release`

**Request Body**:
```json
{
  "guid": "abc123def456",
  "indexerId": 1,
  "movieId": 123,
  "quality": {
    "quality": {
      "id": 3,
      "name": "1080p Bluray"
    },
    "revision": {
      "version": 1,
      "real": 0
    }
  },
  "languages": [
    {
      "id": 1,
      "name": "English"
    }
  ],
  "shouldOverride": false,
  "downloadClientId": null
}
```

**Response**: The ReleaseResource that was grabbed

**Evidence** ([Radarr ReleaseController.cs](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/src/Radarr.Api.V3/Indexers/ReleaseController.cs#L62-L125)):
```csharp
[HttpPost]
[Consumes("application/json")]
public async Task<object> DownloadRelease([FromBody] ReleaseResource release)
{
  var remoteMovie = _remoteMovieCache.Find(GetCacheKey(release));
  
  if (remoteMovie == null)
  {
    throw new NzbDroneClientException(HttpStatusCode.NotFound, 
      "Couldn't find requested release in cache, try searching again");
  }
  
  try
  {
    if (release.ShouldOverride == true)
    {
      Ensure.That(release.MovieId, () => release.MovieId).IsNotNull();
      Ensure.That(release.Quality, () => release.Quality).IsNotNull();
      Ensure.That(release.Languages, () => release.Languages).IsNotNull();
      
      remoteMovie = new RemoteMovie
      {
        Release = remoteMovie.Release,
        ParsedMovieInfo = remoteMovie.ParsedMovieInfo.JsonClone(),
        MovieRequested = remoteMovie.MovieRequested,
        DownloadAllowed = remoteMovie.DownloadAllowed,
        SeedConfiguration = remoteMovie.SeedConfiguration,
        CustomFormats = remoteMovie.CustomFormats,
        CustomFormatScore = remoteMovie.CustomFormatScore,
        MovieMatchType = remoteMovie.MovieMatchType,
        ReleaseSource = remoteMovie.ReleaseSource
      };
      
      remoteMovie.Movie = _movieService.GetMovie(release.MovieId!.Value);
      remoteMovie.ParsedMovieInfo.Quality = release.Quality;
      remoteMovie.Languages = release.Languages;
    }
    
    if (remoteMovie.Movie == null)
    {
      if (release.MovieId.HasValue)
      {
        var movie = _movieService.GetMovie(release.MovieId.Value);
        remoteMovie.Movie = movie;
      }
      else
      {
        throw new NzbDroneClientException(HttpStatusCode.NotFound, 
          "Unable to find matching movie, will need to be manually provided");
      }
    }
    
    await _downloadService.DownloadReport(remoteMovie, release.DownloadClientId);
  }
  catch (ReleaseDownloadException ex)
  {
    _logger.Error(ex, ex.Message);
    throw new NzbDroneClientException(HttpStatusCode.Conflict, 
      "Getting release from indexer failed");
  }
  
  return release;
}
```

---

## 5. REJECTION REASONS & SCORING

### 5.1 Common Rejection Reasons

Radarr/Sonarr evaluate each release against a set of rules and return rejection reasons if the release doesn't meet criteria. These are displayed in the **Rejections** column as a popover.

**Common rejection reasons**:

| Reason | Meaning | Applicable to Books? |
|--------|---------|----------------------|
| `Quality cutoff not met` | Release quality is below the configured quality profile cutoff | ✅ Yes (file format, bitrate) |
| `Custom format score below threshold` | Release custom format score is below minimum required | ✅ Yes (e.g., DRM-free, specific edition) |
| `Language not wanted` | Release language doesn't match profile | ✅ Yes (language preference) |
| `Blocklisted` | Release is on the blocklist (previously failed) | ✅ Yes |
| `Not a Custom Format upgrade for existing file(s)` | Release doesn't improve custom format score over existing file | ✅ Yes |
| `Indexer disabled for automatic search` | Indexer is disabled for automatic searches | ✅ Yes |
| `Indexer disabled for interactive search` | Indexer is disabled for manual searches | ✅ Yes |
| `Release rejected by regex` | Release title matches a rejection regex pattern | ✅ Yes |
| `Minimum seeders not met` | Torrent has fewer seeders than configured minimum | ✅ Yes (peer count) |
| `Minimum age not met` | Release is too new (delay profile) | ✅ Yes |
| `Maximum age exceeded` | Release is too old | ✅ Yes |
| `Size too small` | Release file size is below minimum | ✅ Yes |
| `Size too large` | Release file size exceeds maximum | ✅ Yes |
| `Duplicate` | Release is a duplicate of another candidate | ✅ Yes |

**Evidence** ([Radarr ReleaseResource.cs](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/src/Radarr.Api.V3/Indexers/ReleaseResource.cs#L42)):
```csharp
public IEnumerable<string> Rejections { get; set; }
```

Mapped from DownloadDecision:
```csharp
Rejections = model.Rejections.Select(r => r.Message).ToList(),
```

### 5.2 Scoring Fields

Each release is scored on multiple dimensions:

| Score | Field | Range | Purpose |
|-------|-------|-------|---------|
| **Release Weight** | `releaseWeight` | 0+ | Position in ranked list (lower = better) |
| **Quality Weight** | `qualityWeight` | 0+ | Quality tier score (higher = better quality) |
| **Custom Format Score** | `customFormatScore` | 0+ | Custom format match score (higher = better match) |

**Calculation** ([Radarr ReleaseControllerBase.cs](https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/src/Radarr.Api.V3/Indexers/ReleaseControllerBase.cs#L44-L56)):
```csharp
protected virtual ReleaseResource MapDecision(DownloadDecision decision, int initialWeight)
{
  var release = decision.ToResource();
  
  release.ReleaseWeight = initialWeight;
  
  release.QualityWeight = _qualityProfile.GetIndex(release.Quality.Quality).Index * 100;
  release.QualityWeight += release.Quality.Revision.Real * 10;
  release.QualityWeight += release.Quality.Revision.Version;
  
  return release;
}
```

---

## 6. STATUS BADGES (Movie/Series Page)

### 6.1 Movie Status (Radarr)

On the Radarr movie library page, each movie displays a **status badge** indicating its download state:

| Status | Meaning | Trigger |
|--------|---------|---------|
| **Downloaded** | Movie file exists and meets quality cutoff | Movie file imported and quality ≥ cutoff |
| **Missing** | Movie is monitored but no file exists | Monitored = true, no movie file |
| **Wanted** | Movie is missing and actively being searched | Missing + in search queue |
| **Cutoff Not Met** | Movie file exists but doesn't meet quality cutoff | Movie file exists, quality < cutoff |
| **Unreleased** | Movie hasn't been released yet | Release date in future |
| **Excluded** | Movie is in library but not monitored | Monitored = false |

**Evidence** ([Radarr PR #11346](https://github.com/Radarr/Radarr/pull/11346)):
```
Allows filtering by "Download Status", indicating whether a movie is downloaded, missing, queued, or unreleased.
```

### 6.2 Episode Status (Sonarr)

On the Sonarr series/episode page, each episode displays a **status badge**:

| Status | Meaning | Trigger |
|--------|---------|---------|
| **Downloaded** | Episode file exists and meets quality cutoff | Episode file imported and quality ≥ cutoff |
| **Missing** | Episode is monitored but no file exists | Monitored = true, no episode file |
| **Wanted** | Episode is missing and actively being searched | Missing + in search queue |
| **Cutoff Not Met** | Episode file exists but doesn't meet quality cutoff | Episode file exists, quality < cutoff |
| **Unaired** | Episode hasn't aired yet | Air date in future |
| **Skipped** | Episode is monitored but not searched | Monitored = true, skip = true |
| **Ignored** | Episode is not monitored | Monitored = false |

**Evidence** ([Sonarr Wanted/Missing/CutoffUnmet pages](https://github.com/Sonarr/Sonarr/commit/152f50a1ef977298ef0415ccda6e84d83b37661b)):
```
const WANTED_CUTOFF_UNMET = 'wanted.cutoffUnmet';
const WANTED_MISSING = 'wanted.missing';
```

---

## 7. WANTED PAGE FILTERS

### 7.1 Radarr Wanted Filters

The Radarr **Wanted** section has two tabs:

1. **Missing** — Movies with no file
   - Filters: Monitored, Title, Release Date, Quality, Custom Format Score
   - Bulk actions: Search All, Toggle Monitored, Remove

2. **Cutoff Unmet** — Movies with file below quality cutoff
   - Filters: Monitored, Title, Downloaded Quality, Custom Format Score
   - Bulk actions: Search All, Toggle Monitored, Remove

**Evidence** ([Radarr Wanted/Missing/Missing.tsx](https://github.com/Radarr/Radarr/commit/ef9836d71d79cdefe949c276af4a7604b7e69278)):
```typescript
// Wanted/Missing page shows movies with no file
// Wanted/CutoffUnmet page shows movies with file below cutoff
```

### 7.2 Sonarr Wanted Filters

The Sonarr **Wanted** section has two tabs:

1. **Missing** — Episodes with no file
   - Filters: Series, Season, Episode, Air Date, Quality, Custom Format Score
   - Bulk actions: Search All, Toggle Monitored

2. **Cutoff Unmet** — Episodes with file below quality cutoff
   - Filters: Series, Season, Episode, Downloaded Quality, Custom Format Score
   - Bulk actions: Search All, Toggle Monitored

---

## 8. TRANSLATION TO BOOKOTTER (BOOKS)

### 8.1 Applicable Concepts

| Radarr/Sonarr Concept | BookOtter Equivalent | Notes |
|----------------------|----------------------|-------|
| **Quality Profile** | Format Profile (EPUB, MOBI, PDF, etc.) | Books have format preferences instead of video quality |
| **Quality Cutoff** | Format Cutoff | Minimum acceptable format (e.g., "must be EPUB or better") |
| **Custom Formats** | Edition/Metadata Formats | DRM-free, specific edition, language, file size |
| **Rejection Reasons** | Same | Language, file size, DRM, edition mismatch, etc. |
| **Seeders/Leechers** | Peer count | Applicable to torrent sources |
| **Release Age** | Same | Applicable to all sources |
| **Indexer Flags** | Source flags | e.g., "Freeleech" on torrent sites |
| **Status Badges** | Same | Downloaded, Missing, Wanted, Cutoff Not Met |
| **Automatic Search** | Same | Auto-grab best match per profile |
| **Interactive Search** | Same | Manual review + override capability |

### 8.2 Unique Considerations for Books

1. **Format Complexity**: Books have more format variants (EPUB, MOBI, PDF, AZW3, etc.) than video (1080p, 720p, etc.)
2. **Edition Sensitivity**: Users often care about specific editions (hardcover, paperback, first edition) — more nuanced than video quality
3. **DRM**: E-books often have DRM; users may want DRM-free only
4. **File Size**: Less critical than video, but still relevant (e.g., avoid bloated PDFs)
5. **Language**: Critical for books; more granular than video (original language vs translation)
6. **Metadata**: Book metadata (author, ISBN, publication date) is more variable than movie/series metadata

### 8.3 Recommended BookOtter Columns (Interactive Search)

Adapt Radarr/Sonarr's table to books:

| Column | Data | Purpose |
|--------|------|---------|
| **Source** | String | Hardcover, Prowlarr indexer name, etc. |
| **Age** | Integer (days) | Release/upload age |
| **Title** | String | Book title + author |
| **Indexer** | String | Source (Prowlarr indexer) |
| **History** | Icon | Grabbed/failed/blocklisted |
| **Size** | Long (bytes) | File size |
| **Peers** | Integer | Torrent peer count (if applicable) |
| **Language** | List | Book language(s) |
| **Format** | String | EPUB, MOBI, PDF, etc. |
| **Edition** | String | Hardcover, Paperback, First Edition, etc. |
| **DRM** | Boolean | DRM-free or not |
| **Custom Format Score** | Integer | Edition/metadata match score |
| **Rejections** | List | Why release was rejected |
| **Download** | Buttons | Grab + Override |

---

## 9. IMPLEMENTATION CHECKLIST FOR BOOKOTTER

- [ ] **Automatic Search Button**: Trigger `POST /api/command` with book ID
- [ ] **Interactive Search Modal**: Fetch releases via `GET /api/release?bookId={id}`
- [ ] **Results Table**: Implement columns from section 8.3
- [ ] **Rejection Popover**: Display rejection reasons from API response
- [ ] **Custom Format Score Tooltip**: Show which formats matched
- [ ] **Grab Button**: `POST /api/release` with `guid`, `indexerId`
- [ ] **Override Button**: `POST /api/release` with `shouldOverride: true`, custom format/language/edition
- [ ] **Status Badges**: Downloaded, Missing, Wanted, Cutoff Not Met
- [ ] **Wanted Page Filters**: Missing tab + Cutoff Unmet tab with bulk search
- [ ] **Blocklist Integration**: Allow blocklisting + re-search from interactive search

---

## 10. REFERENCES

### Radarr Source Files
- **ReleaseController.cs**: https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/src/Radarr.Api.V3/Indexers/ReleaseController.cs
- **ReleaseResource.cs**: https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/src/Radarr.Api.V3/Indexers/ReleaseResource.cs
- **MovieSearchCell.tsx**: https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/frontend/src/Movie/MovieSearchCell.tsx
- **InteractiveSearchRow.tsx**: https://github.com/Radarr/Radarr/blob/92268767921bddd1625c6acb80b704464b5feb0a/frontend/src/InteractiveSearch/InteractiveSearchRow.tsx

### Sonarr Source Files
- **ReleaseController.cs (V3)**: https://github.com/Sonarr/Sonarr/blob/bf5d48c76a6a793b7d2adc540bb11d9c51bcc3cb/src/Sonarr.Api.V3/Indexers/ReleaseController.cs
- **ReleaseResource.cs (V5)**: https://github.com/Sonarr/Sonarr/blob/bf5d48c76a6a793b7d2adc540bb11d9c51bcc3cb/src/Sonarr.Api.V5/Release/ReleaseResource.cs
- **EpisodeSearch.tsx**: https://github.com/Sonarr/Sonarr/blob/bf5d48c76a6a793b7d2adc540bb11d9c51bcc3cb/frontend/src/Episode/Search/EpisodeSearch.tsx
- **InteractiveSearchRow.tsx**: https://github.com/Sonarr/Sonarr/blob/bf5d48c76a6a793b7d2adc540bb11d9c51bcc3cb/frontend/src/InteractiveSearch/InteractiveSearchRow.tsx

### Servarr Wiki
- **Radarr FAQ**: https://wiki.servarr.com/radarr/faq
- **Radarr Library**: https://wiki.servarr.com/radarr/library
- **Sonarr FAQ**: https://wiki.servarr.com/sonarr/faq
- **Sonarr Wanted**: https://wiki.servarr.com/sonarr/wanted

---

**Document Version**: 1.0  
**Last Updated**: April 27, 2026  
**Status**: Ready for BookOtter UX redesign specification

# MDM Link 0.1.1

Source search/resolution backend for MDM Flix. This first batch provides an extensible API, two built-in adapters and three configurable stream-provider slots.

## Setup and modes

In Flix, select **MDM Link** as Scraper Provider. **Auto** continues to use CocoScrapers, preserving its existing behavior. Provider Settings opens Link's settings when Link is selected. Link also has its own Program add-on menu for settings, AllDebrid authorisation/account check/local disconnect and diagnostics.

- **Free:** Internet Archive and configured direct stream providers. No local debrid account is required; torrent results are excluded.
- **Debrid:** debrid-capable provider results only, resolved through an enabled authorised AllDebrid account.
- **Combined:** both source types when available, with debrid first and quality ordering within each group. Without enabled AllDebrid credentials, this mode returns free results only.

AllDebrid credentials are copied from Flix once inside Kodi when Link is first selected. Existing Link credentials are never overwritten. Disabled authorisation stays disabled. Disconnecting Link prevents automatic reimport and does not change Flix/CocoScrapers's separate settings. After the initial copy, each provider's Tools actions target its own account settings. No credentials are sent to scraper search services.

## Built-in providers

**Internet Archive:** searches public movie metadata by exact title/known aliases and year, then offers downloadable video files. TV matching requires the show identity plus matching season/episode coordinates or an exact episode filename. Private/restricted files, samples and trailers are excluded. Coverage is limited to indexed, identifiable items, including classic films/TV; no result for a title is a normal outcome. Source language and quality depend on the uploaded file. Episode searches first target the requested coordinates or episode title, then fall back to the show if needed. Hits use stable download/identifier ordering. Search reads at most five matching item records within the overall deadline.

**Torrentio:** retrieves torrent metadata using IMDb movie IDs or show ID/season/episode. Link creates normalised magnet candidates and resolves only the user's selected candidate through AllDebrid. This adapter queries Torrentio's public service independently of CocoScrapers; it is not a copy of all underlying web scrapers. No torrent client/download engine is provided for free mode.

**Additional stream providers:** enter up to three Stremio-compatible provider base or manifest URLs. Addresses are masked because configured paths can contain secrets; diagnostics show slot IDs only. Providers must offer `/stream/movie/{imdb}.json` and/or `/stream/series/{imdb}:{season}:{episode}.json`. Direct HTTP(S) video and `infoHash` torrent records are supported. Use direct providers that offer free streams for the free path; upstream subscription entitlement cannot be inferred from a URL. Browser links, DRM, archive/NZB responses, YouTube IDs and proxy/header-dependent streams require future adapters and are currently skipped. Query-string configuration is not supported; use the provider's documented base/configured path URL. Changing an address invalidates its previously listed sources.

## Reliability and limitations

The versioned `mdmlink.api` interface accepts movie/episode identity, returns normalised sources and resolves a selected source. At most five daemon workers search concurrently with a 30-second overall limit, bounded metadata response sizes and request timeouts. Cancelling returns promptly; an already running network read can finish in the background. Adapter failures are isolated, completed provider results remain available, and diagnostics record only provider ID/status/count and final free/debrid/total counts. Equivalent magnets and direct URLs are deduplicated within their access type.

Flix retains its 30-minute source sessions, manual choice and one-candidate autoplay. Autoplay does not silently submit additional torrents or fall back between access modes. Select another source manually after a failure. AllDebrid availability remains unchecked until selection; uncached selections may create account transfers. Cancellation/timeouts do not delete transfers. AllDebrid preparation limits remain 45 seconds total after source search plus an in-flight request.

Current support is AllDebrid, direct HTTP(S) video and magnet metadata. More scraper/host/service adapters are planned in tested batches. Provider responsiveness does not prove playback or universal title coverage. PC acceptance, Firestick and public release are recorded separately in the development roadmap.

## References

- Internet Archive metadata: https://archive.org/developers/md-read.html
- Internet Archive search: https://archive.org/developers/item-search-apis.html
- Torrentio: https://github.com/TheBeastLT/torrentio-scraper
- Stremio stream responses: https://stremio.github.io/stremio-addon-sdk/api/responses/stream.html
- AllDebrid API: https://docs.alldebrid.com/


## Device tuning
Device-local profiles, reversible tuning, bounded worker/search/request settings and reported-quality limits. Light Flix artwork reduces image size and omits catalogue fanart. Unknown quality is configurable. TV/decoder capability is not inferred from the Kodi screen. Portable builds exclude device tuning; external scraper requests may finish after a deadline. No bandwidth ranking or cache/widget tuning in this release.
Use Conf Device profiles to preview/apply Low memory or Balanced and undo the last application. Low memory: Flix 2 workers, Link 1 worker, 90s search, 30s requests, Light artwork. Balanced: Flix 6 / Link 5 workers, 45s / 30s search, 15s requests, Standard artwork. Total memory at or below 2048 MB suggests Low memory; free-memory fluctuations do not reapply settings. Quality filtering happens after provider retrieval and again before resolving; both Flix and Link limits apply to Link playback. Set unknown quality to Hide for strict filtering, at the cost of fewer results. This is a preset, not a measured performance optimisation.


## Connection and file-size preferences
Connection speed, maximum reported GiB, explicit missing-metadata controls, estimated average bitrate with 25% reserve, and Quality/Connection/Smallest ordering. Debrid priority preserved; manual selection and single-source autoplay use the same limits. Device-local preferences; no speed probe or stability guarantee. Whole episode-pack sizes do not produce episode bitrate estimates. Conf provides preview/apply/undo for both addons.
Size uses GiB (1024^3 bytes), not decimal GB. Mbps uses 1,000,000 bits/s. Enter your own connection capacity; 0 disables connection classification. Average bitrate = reported size * 8 / title duration; 75% of entered speed is the budget. Variable bitrate peaks, host throughput and runtime accuracy can differ. Connection order: debrid first, then within each access group Fits estimate, Unknown, Above budget; quality breaks ties. Smallest order: debrid first, smaller reported sizes first, unknown last. A positive size cap filters size before sorting, including in Connection mode. Hide unknown size only acts with a positive size cap; Hide unknown bitrate/Above budget only acts with a positive connection. Defaults preserve quality order without new filtering. Torrent/package-size caps are conservative; an excluded pack may contain smaller eligible files. Current source limits are checked again before resolution and against debrid file/stream metadata where supplied. Returned metadata is not a verified download quota.


## Playback reliability repair

The selected debrid file keeps the release's reported resolution when the filename omits it. An explicit file resolution takes precedence and higher quality remains subject to the chosen cap. Size and bitrate checks use actual file bytes where supplied; unknown metadata stays unknown. File-selection errors distinguish unavailable/no-video file lists, an unmatched episode and specific quality/size/connection exclusions. Preferences from both Flix and the selected provider are respected.

AllDebrid readiness and delayed-link preparation share one 45-second resolution budget, after the separately bounded source search. Requests use the smaller of their existing timeout and remaining resolution budget. Progress identifies checking, downloading/preparing, file matching and link generation; cancellation remains available. Transfers are not deleted on timeout. Autoplay still resolves only the top ranked source, without bulk transfers or a new fallback loop. Ranking is not an availability guarantee.

The earlier 2 Mbps and 2 GiB test values are restrictive preferences, not a measured connection. A 2 Mbps input has a 1.5 Mbps estimated budget. Above-budget filtering depends on the Show/Hide choice. Use actual measured capacity, or 0 to disable that estimate; retain a file-size cap if it is intentional. This release never resets user preferences.

The preparation budget excludes time spent deliberately choosing among matching files. An in-flight network call uses its remaining timeout; cancellation is checked between those calls and during preparation waits.

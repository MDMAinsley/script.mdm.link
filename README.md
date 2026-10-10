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

Flix retains its 30-minute source sessions, manual choice and one-candidate autoplay. Autoplay does not silently submit additional torrents or fall back between access modes. Select another source manually after a failure. AllDebrid availability remains unchecked until selection; uncached selections may create account transfers. Cancellation/timeouts do not delete transfers. AllDebrid preparation limits remain 60 seconds per stage plus an in-flight request.

Current support is AllDebrid, direct HTTP(S) video and magnet metadata. More scraper/host/service adapters are planned in tested batches. Provider responsiveness does not prove playback or universal title coverage. PC acceptance, Firestick and public release are recorded separately in the development roadmap.

## References

- Internet Archive metadata: https://archive.org/developers/md-read.html
- Internet Archive search: https://archive.org/developers/item-search-apis.html
- Torrentio: https://github.com/TheBeastLT/torrentio-scraper
- Stremio stream responses: https://stremio.github.io/stremio-addon-sdk/api/responses/stream.html
- AllDebrid API: https://docs.alldebrid.com/

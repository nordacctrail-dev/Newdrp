const mangayomiSources = [
  {
    "name": "Towkai",
    "id": 918273645,
    "baseUrl": "http://mm.towkai.com",
    "lang": "en",
    "typeSource": "single",
    "iconUrl": "http://mm.towkai.com/uploads/system_logo/logo_629599c462f85.png",
    "dateFormat": "",
    "dateFormatLocale": "",
    "isNsfw": false,
    "hasCloudflare": false,
    "sourceCodeUrl": "https://raw.githubusercontent.com/nordacctrail-dev/Newdrp/main/towkai.js",
    "apiUrl": "",
    "version": "1.0.0",
    "isManga": false,
    "itemType": 1,
    "isFullData": false,
    "appMinVerReq": "0.5.0",
    "additionalParams": "",
    "sourceCodeLanguage": 1,
    "notes": "",
    "pkgPath": "Newdrp/main/towkai.js",
  },
];

class DefaultExtension extends MProvider {

  // ───────────────────────────────────────────────────────────────────────────
  // Basic helpers
  // ───────────────────────────────────────────────────────────────────────────

  get ua() {
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36";
  }

  getHeaders(referer) {
    return {
      "User-Agent": this.ua,
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9",
      "Referer": referer || this.source.baseUrl + "/",
    };
  }

  absoluteUrl(url) {
    if (!url) return "";

    url = url.trim();

    if (url.startsWith("http://") || url.startsWith("https://")) {
      return url;
    }

    if (url.startsWith("//")) {
      return "http:" + url;
    }

    if (url.startsWith("/")) {
      return this.source.baseUrl + url;
    }

    return this.source.baseUrl + "/" + url;
  }

  cleanText(text) {
    if (!text) return "";

    return text
      .replace(/<script[\s\S]*?<\/script>/gi, "")
      .replace(/<style[\s\S]*?<\/style>/gi, "")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&quot;/gi, "\"")
      .replace(/&#39;/gi, "'")
      .replace(/&#x27;/gi, "'")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/\s+/g, " ")
      .trim();
  }

  decodeHtml(text) {
    if (!text) return "";

    return text
      .replace(/&amp;/gi, "&")
      .replace(/&quot;/gi, "\"")
      .replace(/&#39;/gi, "'")
      .replace(/&#x27;/gi, "'")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/&nbsp;/gi, " ")
      .trim();
  }

  // ───────────────────────────────────────────────────────────────────────────
  // HTTP
  // ───────────────────────────────────────────────────────────────────────────

  async getPage(url, referer) {
    const client = new Client();

    try {
      const res = await client.get(
        url,
        this.getHeaders(referer || this.source.baseUrl + "/")
      );

      if (!res) return "";
      if (res.statusCode && (res.statusCode < 200 || res.statusCode >= 400)) {
        return "";
      }

      return res.body || "";
    } catch (e) {
      return "";
    }
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Parse movie / series cards
  // ───────────────────────────────────────────────────────────────────────────

  parseCards(html) {
    const list = [];
    const seen = {};

    if (!html) return list;

    const blocks = html
      .split('class="latest-movie-img-container')
      .slice(1);

    for (const block of blocks) {

      let name = "";
      let url = "";
      let imageUrl = "";

      // Poster
      if (block.includes('data-src="')) {
        imageUrl = block
          .substringAfter('data-src="')
          .substringBefore('"')
          .trim();
      }

      // Fallback poster
      if (!imageUrl && block.includes('src="')) {
        imageUrl = block
          .substringAfter('src="')
          .substringBefore('"')
          .trim();
      }

      // Watch URL
      if (block.includes('href="')) {
        const hrefs = block.split('href="');

        for (let i = 1; i < hrefs.length; i++) {
          const candidate = hrefs[i]
            .substringBefore('"')
            .trim();

          if (candidate.includes("/watch/")) {
            url = candidate;
            break;
          }
        }
      }

      // Title
      if (block.includes('class="movie-title"')) {
        name = block
          .substringAfter('class="movie-title"')
          .substringAfter("<h3>")
          .substringAfter("<a")
          .substringAfter(">")
          .substringBefore("</a>")
          .trim();
      }

      // Fallback title
      if (!name && block.includes("<h3>")) {
        name = block
          .substringAfter("<h3>")
          .substringAfter(">")
          .substringBefore("</a>")
          .trim();
      }

      name = this.cleanText(name);
      url = this.absoluteUrl(url);
      imageUrl = this.absoluteUrl(imageUrl);

      if (!url || !name) continue;
      if (seen[url]) continue;

      seen[url] = true;

      list.push({
        "name": name,
        "url": url,
        "imageUrl": imageUrl,
      });
    }

    return list;
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Popular
  // ───────────────────────────────────────────────────────────────────────────

  async getPopular(page) {
    try {
      const n = page || 1;

      let url =
        this.source.baseUrl +
        "/movies_details.html?sort=top";

      if (n > 1) {
        url += "&page=" + n;
      }

      const html = await this.getPage(
        url,
        this.source.baseUrl + "/"
      );

      if (!html) {
        return {
          "list": [],
          "hasNextPage": false,
        };
      }

      const list = this.parseCards(html);

      return {
        "list": list,
        "hasNextPage": false,
      };

    } catch (e) {
      return {
        "list": [],
        "hasNextPage": false,
      };
    }
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Latest
  // ───────────────────────────────────────────────────────────────────────────

  async getLatestUpdates(page) {
    try {
      const n = page || 1;

      let url =
        this.source.baseUrl +
        "/movies_details.html?sort=added";

      if (n > 1) {
        url += "&page=" + n;
      }

      const html = await this.getPage(
        url,
        this.source.baseUrl + "/"
      );

      if (!html) {
        return {
          "list": [],
          "hasNextPage": false,
        };
      }

      const list = this.parseCards(html);

      return {
        "list": list,
        "hasNextPage": false,
      };

    } catch (e) {
      return {
        "list": [],
        "hasNextPage": false,
      };
    }
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Search
  // ───────────────────────────────────────────────────────────────────────────

  async search(query, page, filters) {
    try {
      const q = (query || "").trim();

      if (!q) {
        return {
          "list": [],
          "hasNextPage": false,
        };
      }

      const n = page || 1;

      let url =
        this.source.baseUrl +
        "/search?q=" +
        encodeURIComponent(q);

      if (n > 1) {
        url += "&page=" + n;
      }

      const html = await this.getPage(
        url,
        this.source.baseUrl + "/"
      );

      if (!html) {
        return {
          "list": [],
          "hasNextPage": false,
        };
      }

      let list = this.parseCards(html);

      // Optional type filter
      if (filters && Array.isArray(filters)) {

        for (const filter of filters) {

          if (
            filter &&
            filter.type_name === "SelectFilter" &&
            filter.name === "Type" &&
            filter.state > 0
          ) {

            const selected =
              filter.values[filter.state];

            if (!selected) continue;

            const value = selected.value;

            if (value === "MOVIE" || value === "SERIES") {

              const filtered = [];

              for (const item of list) {

                if (value === "MOVIE") {

                  // A series normally has episode cards.
                  // We don't remove the result here because search
                  // itself doesn't expose a completely reliable type field.
                  filtered.push(item);

                } else if (value === "SERIES") {

                  filtered.push(item);
                }
              }

              list = filtered;
            }
          }
        }
      }

      return {
        "list": list,
        "hasNextPage": false,
      };

    } catch (e) {
      return {
        "list": [],
        "hasNextPage": false,
      };
    }
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Episode parser
  // ───────────────────────────────────────────────────────────────────────────

  parseEpisodes(html) {
    const chapters = [];
    const seen = {};

    if (!html) return chapters;

    /*
      Actual Towkai structure:

      <figure class="figure">
        <a href="http://mm.towkai.com/watch/spiderman.html?key=xxxx">
          <div>
            <img ... data-src="..." alt="Episode title" />
          </div>
          <figcaption class="figure-caption " >
            Episode title
          </figcaption>
        </a>
      </figure>
    */

    const blocks = html
      .split('figure class="figure"')
      .slice(1);

    for (const block of blocks) {

      let episodeUrl = "";
      let episodeName = "";
      let episodeImage = "";

      // Find watch URL specifically
      if (block.includes('href="')) {

        const hrefs = block.split('href="');

        for (let i = 1; i < hrefs.length; i++) {

          const candidate = hrefs[i]
            .substringBefore('"')
            .trim();

          if (candidate.includes("/watch/")) {
            episodeUrl = candidate;
            break;
          }
        }
      }

      // Figure caption
      if (block.includes("<figcaption")) {

        episodeName = block
          .substringAfter("<figcaption")
          .substringAfter(">")
          .substringBefore("</figcaption")
          .trim();
      }

      // Remove accidental HTML
      episodeName = this.cleanText(episodeName);

      // Image alt fallback
      if (!episodeName && block.includes('alt="')) {

        episodeName = block
          .substringAfter('alt="')
          .substringBefore('"')
          .trim();

        episodeName = this.cleanText(episodeName);
      }

      // Image
      if (block.includes('data-src="')) {

        episodeImage = block
          .substringAfter('data-src="')
          .substringBefore('"')
          .trim();

      } else if (block.includes('src="')) {

        episodeImage = block
          .substringAfter('src="')
          .substringBefore('"')
          .trim();
      }

      episodeUrl = this.absoluteUrl(episodeUrl);
      episodeImage = this.absoluteUrl(episodeImage);

      if (!episodeUrl) continue;
      if (seen[episodeUrl]) continue;

      seen[episodeUrl] = true;

      chapters.push({
        "name": episodeName || "Episode",
        "url": episodeUrl,
        "imageUrl": episodeImage,
        "isFiller": false,
      });
    }

    return chapters;
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Meta helper
  // ───────────────────────────────────────────────────────────────────────────

  getMeta(html, metaName) {
    if (!html) return "";

    const pattern =
      new RegExp(
        '<meta[^>]+name=["\']' +
        metaName +
        '["\'][^>]+content=["\']([^"\']*)["\']',
        "i"
      );

    const match = html.match(pattern);

    if (match) {
      return this.decodeHtml(match[1]);
    }

    return "";
  }

  getProperty(html, propertyName) {
    if (!html) return "";

    const pattern =
      new RegExp(
        '<meta[^>]+property=["\']' +
        propertyName +
        '["\'][^>]+content=["\']([^"\']*)["\']',
        "i"
      );

    const match = html.match(pattern);

    if (match) {
      return this.decodeHtml(match[1]);
    }

    return "";
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Detail information
  // ───────────────────────────────────────────────────────────────────────────

  extractDetailInfo(html, url) {

    let title = "";
    let description = "";
    let imageUrl = "";
    let author = "";
    let genre = [];

    // ── Title ────────────────────────────────────────────────

    if (html.includes("<title>")) {

      title = html
        .substringAfter("<title>")
        .substringBefore("</title>")
        .trim();

      title = this.cleanText(title);
    }

    if (!title) {
      title = this.getProperty(html, "og:title");
    }

    if (!title) {
      title = this.getMeta(html, "twitter:title");
    }

    if (!title && html.includes("<h1")) {

      title = html
        .substringAfter("<h1")
        .substringAfter(">")
        .substringBefore("</h1>")
        .trim();

      title = this.cleanText(title);
    }

    // ── Description ─────────────────────────────────────────

    description = this.getMeta(html, "description");

    if (!description) {
      description = this.getProperty(html, "og:description");
    }

    if (!description) {
      description = this.getMeta(html, "twitter:description");
    }

    // Fallback visible description
    if (!description && html.includes('<h5 style="color:white;">')) {

      description = html
        .substringAfter('<h5 style="color:white;">')
        .substringBefore("</h5>")
        .trim();

      description = this.cleanText(description);
    }

    // ── Cover image ─────────────────────────────────────────

    imageUrl = this.getProperty(html, "og:image");

    if (!imageUrl) {
      imageUrl = this.getMeta(html, "twitter:image");
    }

    if (!imageUrl && html.includes('class="col-md-3 m-t-10"')) {

      imageUrl = html
        .substringAfter('class="col-md-3 m-t-10"')
        .substringAfter('src="')
        .substringBefore('"')
        .trim();
    }

    imageUrl = this.absoluteUrl(imageUrl);

    // ── Author ───────────────────────────────────────────────

    author = this.getMeta(html, "author");

    // ── Genre ────────────────────────────────────────────────

    /*
      Try common Towkai genre links if present.
    */

    if (html.includes("/genre/")) {

      const parts = html.split("/genre/");

      for (let i = 1; i < parts.length; i++) {

        let section = parts[i];

        if (!section.includes(">")) continue;

        let g = section
          .substringAfter(">")
          .substringBefore("</a>")
          .trim();

        g = this.cleanText(g);

        if (
          g &&
          g.length < 50 &&
          genre.indexOf(g) === -1
        ) {
          genre.push(g);
        }
      }
    }

    return {
      "name": title || "Unknown",
      "description": description || "",
      "imageUrl": imageUrl || "",
      "author": author || "",
      "genre": genre,
      "link": url,
    };
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Detail
  // ───────────────────────────────────────────────────────────────────────────

  async getDetail(url) {

    if (!url) {
      throw new Error("Towkai detail URL is empty");
    }

    const html = await this.getPage(
      url,
      this.source.baseUrl + "/"
    );

    if (!html) {
      throw new Error("Unable to load Towkai detail page");
    }

    const info = this.extractDetailInfo(
      html,
      url
    );

    const chapters = this.parseEpisodes(html);

    /*
      A movie page doesn't have the episode carousel.

      Therefore expose the page itself as a single
      playable chapter.
    */

    if (chapters.length === 0) {

      chapters.push({
        "name": "Movie",
        "url": url,
        "isFiller": false,
      });

    } else {

      // Newest episode first
      chapters.reverse();
    }

    return {
      "name": info.name,
      "description": info.description,
      "author": info.author,
      "genre": info.genre,
      "status": 1,
      "imageUrl": info.imageUrl,
      "link": info.link,
      "chapters": chapters,
    };
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Extract Video.js source
  // ───────────────────────────────────────────────────────────────────────────

  extractVideoSource(html) {

    if (!html) return "";

    let videoUrl = "";

    /*
      Actual Towkai player:

      sources: [{
          src: 'http://.../index.m3u8',
          type: 'application/x-mpegURL'
      }]
    */

    // Primary exact parser
    if (html.includes("sources: [{")) {

      const section = html
        .substringAfter("sources: [{");

      if (section.includes("src:")) {

        const srcPart = section
          .substringAfter("src:")
          .trim();

        if (srcPart.startsWith("'")) {

          videoUrl = srcPart
            .substringAfter("'")
            .substringBefore("'")
            .trim();

        } else if (srcPart.startsWith("\"")) {

          videoUrl = srcPart
            .substringAfter("\"")
            .substringBefore("\"")
            .trim();
        }
      }
    }

    // Direct single-quote fallback
    if (!videoUrl && html.includes("src: '")) {

      const parts = html.split("src: '");

      for (let i = 1; i < parts.length; i++) {

        const candidate = parts[i]
          .substringBefore("'")
          .trim();

        if (
          candidate.includes(".m3u8") ||
          candidate.includes(".mp4")
        ) {
          videoUrl = candidate;
          break;
        }
      }
    }

    // Double quote fallback
    if (!videoUrl && html.includes('src: "')) {

      const parts = html.split('src: "');

      for (let i = 1; i < parts.length; i++) {

        const candidate = parts[i]
          .substringBefore('"')
          .trim();

        if (
          candidate.includes(".m3u8") ||
          candidate.includes(".mp4")
        ) {
          videoUrl = candidate;
          break;
        }
      }
    }

    // HTML video source fallback
    if (!videoUrl && html.includes("<source")) {

      const sourceBlocks =
        html.split("<source").slice(1);

      for (const block of sourceBlocks) {

        if (!block.includes('src="')) continue;

        const candidate = block
          .substringAfter('src="')
          .substringBefore('"')
          .trim();

        if (
          candidate.includes(".m3u8") ||
          candidate.includes(".mp4")
        ) {
          videoUrl = candidate;
          break;
        }
      }
    }

    // Regex fallback for m3u8
    if (!videoUrl) {

      const match = html.match(
        /https?:\/\/[^'"<>\s]+\.m3u8(?:[^'"<>\s]*)?/i
      );

      if (match) {
        videoUrl = match[0];
      }
    }

    return this.absoluteUrl(videoUrl);
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Resolve HLS master playlist
  // ───────────────────────────────────────────────────────────────────────────

  async resolveMasterPlaylist(masterUrl, headers) {

    try {

      const client = new Client();

      const res = await client.get(
        masterUrl,
        headers || {}
      );

      if (!res || !res.body) {
        return [];
      }

      const body = res.body;

      if (!body.includes("#EXT-X-STREAM-INF")) {
        return [];
      }

      const lines =
        body.split("\n");

      const variants = [];

      const base =
        masterUrl.substring(
          0,
          masterUrl.lastIndexOf("/") + 1
        );

      for (let i = 0; i < lines.length; i++) {

        const line =
          lines[i].trim();

        if (
          !line.startsWith(
            "#EXT-X-STREAM-INF"
          )
        ) {
          continue;
        }

        let quality = "Auto";

        const resolution =
          line.match(
            /RESOLUTION=\d+x(\d+)/i
          );

        if (resolution) {
          quality =
            resolution[1] + "p";
        }

        for (
          let j = i + 1;
          j < lines.length;
          j++
        ) {

          let stream =
            lines[j].trim();

          if (!stream) continue;

          if (stream.startsWith("#")) {
            continue;
          }

          if (
            stream.startsWith("http://") ||
            stream.startsWith("https://")
          ) {
            variants.push({
              "url": stream,
              "quality": quality,
            });
          } else if (stream.startsWith("/")) {
            variants.push({
              "url":
                this.source.baseUrl +
                stream,
              "quality": quality,
            });
          } else {
            variants.push({
              "url":
                base +
                stream,
              "quality": quality,
            });
          }

          break;
        }
      }

      variants.sort(function(a, b) {

        return (
          (parseInt(b.quality) || 0) -
          (parseInt(a.quality) || 0)
        );

      });

      return variants;

    } catch (e) {

      return [];
    }
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Video list
  // ───────────────────────────────────────────────────────────────────────────

  async getVideoList(url) {

    if (!url || url === "n/a") {
      return [];
    }

    try {

      /*
        IMPORTANT:

        The episode URL itself is the Towkai watch page:

        /watch/spiderman.html?key=xxxxxxxx

        We load that exact page and extract its
        Video.js source.
      */

      const html = await this.getPage(
        url,
        this.source.baseUrl + "/"
      );

      if (!html) {
        return [];
      }

      const videoUrl =
        this.extractVideoSource(html);

      if (!videoUrl) {
        return [];
      }

      /*
        Towkai normally returns:

        http://100.64.64.11:80/.../index.m3u8

        or:

        http://ms.towkai.com:80/.../index.m3u8
      */

      const streams = [];

      const headers = {
        "User-Agent": this.ua,
        "Referer": url,
      };

      /*
        Try master playlist first.

        If it contains multiple qualities, expose them
        separately.
      */

      if (
        videoUrl.includes(".m3u8")
      ) {

        const variants =
          await this.resolveMasterPlaylist(
            videoUrl,
            headers
          );

        if (variants.length > 0) {

          for (const variant of variants) {

            streams.push({
              "url": variant.url,
              "originalUrl": videoUrl,
              "quality":
                variant.quality +
                " [Towkai]",
              "headers": headers,
              "subtitles": [],
            });
          }

          return streams;
        }
      }

      // Normal single HLS stream
      streams.push({
        "url": videoUrl,
        "originalUrl": videoUrl,
        "quality":
          videoUrl.includes(".m3u8")
            ? "HLS [Towkai]"
            : "Auto",
        "headers": headers,
        "subtitles": [],
      });

      return streams;

    } catch (e) {

      return [];
    }
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Headers
  // ───────────────────────────────────────────────────────────────────────────

  getHeaders() {
    return {};
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Latest support
  // ───────────────────────────────────────────────────────────────────────────

  get supportsLatest() {
    return true;
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Optional methods
  // ───────────────────────────────────────────────────────────────────────────

  async getPageList(url) {
    return [];
  }

  async getHtmlContent(url) {
    return "";
  }

  async cleanHtmlContent(html) {
    return html;
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Filters
  // ───────────────────────────────────────────────────────────────────────────

  getFilterList() {
    return [];
  }

  // ───────────────────────────────────────────────────────────────────────────
  // Preferences
  // ───────────────────────────────────────────────────────────────────────────

  getSourcePreferences() {
    return [];
  }
}

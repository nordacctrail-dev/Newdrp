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
    "sourceCodeUrl": "https://raw.githubusercontent.com/nordacctrail-dev/Newdrp/refs/heads/main/towkai.js",
    "apiUrl": "",
    "version": "0.0.8",
    "isManga": false,
    "itemType": 1,
    "isFullData": false,
    "appMinVerReq": "0.5.0",
    "additionalParams": "",
    "sourceCodeLanguage": 1,
    "notes": "",
    "pkgPath": "towkai/default",
  },
];

class DefaultExtension extends MProvider {

  get baseUrl() {
    return this.source.baseUrl;
  }

  async getPopular(page) {
    const client = new Client();

    try {
      const res = await client.get(
        this.source.baseUrl + "/movies_details.html?sort=top"
      );

      if (!res || !res.body) {
        return { list: [], hasNextPage: false };
      }

      const html = res.body;
      const list = [];

      const blocks = html
        .split('class="latest-movie-img-container')
        .slice(1);

      for (const block of blocks) {
        let imageUrl = "";
        let url = "";
        let name = "";

        if (block.includes('data-src="')) {
          imageUrl = block
            .substringAfter('data-src="')
            .substringBefore('"')
            .trim();
        }

        if (block.includes('href="')) {
          url = block
            .substringAfter('href="')
            .substringBefore('"')
            .trim();
        }

        if (block.includes('class="movie-title"')) {
          name = block
            .substringAfter('class="movie-title"')
            .substringAfter("<h3>")
            .substringAfter("<a")
            .substringAfter(">")
            .substringBefore("</a>")
            .trim();
        }

        if (url && name) {
          if (!url.startsWith("http")) {
            url = this.source.baseUrl + "/" + url.replace(/^\/+/, "");
          }

          if (imageUrl && !imageUrl.startsWith("http")) {
            imageUrl = this.source.baseUrl + "/" + imageUrl.replace(/^\/+/, "");
          }

          list.push({
            name: name,
            url: url,
            imageUrl: imageUrl,
          });
        }
      }

      return {
        list: list,
        hasNextPage: false,
      };
    } catch (e) {
      return {
        list: [],
        hasNextPage: false,
      };
    }
  }

  async getLatestUpdates(page) {
    const client = new Client();

    try {
      const res = await client.get(
        this.source.baseUrl + "/movies_details.html?sort=added"
      );

      if (!res || !res.body) {
        return { list: [], hasNextPage: false };
      }

      const html = res.body;
      const list = [];

      const blocks = html
        .split('class="latest-movie-img-container')
        .slice(1);

      for (const block of blocks) {
        let imageUrl = "";
        let url = "";
        let name = "";

        if (block.includes('data-src="')) {
          imageUrl = block
            .substringAfter('data-src="')
            .substringBefore('"')
            .trim();
        }

        if (block.includes('href="')) {
          url = block
            .substringAfter('href="')
            .substringBefore('"')
            .trim();
        }

        if (block.includes('class="movie-title"')) {
          name = block
            .substringAfter('class="movie-title"')
            .substringAfter("<h3>")
            .substringAfter("<a")
            .substringAfter(">")
            .substringBefore("</a>")
            .trim();
        }

        if (url && name) {
          if (!url.startsWith("http")) {
            url = this.source.baseUrl + "/" + url.replace(/^\/+/, "");
          }

          if (imageUrl && !imageUrl.startsWith("http")) {
            imageUrl = this.source.baseUrl + "/" + imageUrl.replace(/^\/+/, "");
          }

          list.push({
            name: name,
            url: url,
            imageUrl: imageUrl,
          });
        }
      }

      return {
        list: list,
        hasNextPage: false,
      };
    } catch (e) {
      return {
        list: [],
        hasNextPage: false,
      };
    }
  }

  async search(query, page, filters) {
    const client = new Client();

    try {
      const searchUrl =
        this.source.baseUrl +
        "/search?q=" +
        encodeURIComponent(query || "");

      const res = await client.get(searchUrl);

      if (!res || !res.body) {
        return {
          list: [],
          hasNextPage: false,
        };
      }

      const html = res.body;
      const list = [];

      const blocks = html
        .split('class="latest-movie-img-container')
        .slice(1);

      for (const block of blocks) {
        let imageUrl = "";
        let url = "";
        let name = "";

        if (block.includes('data-src="')) {
          imageUrl = block
            .substringAfter('data-src="')
            .substringBefore('"')
            .trim();
        }

        if (block.includes('href="')) {
          url = block
            .substringAfter('href="')
            .substringBefore('"')
            .trim();
        }

        if (block.includes('class="movie-title"')) {
          name = block
            .substringAfter('class="movie-title"')
            .substringAfter("<h3>")
            .substringAfter("<a")
            .substringAfter(">")
            .substringBefore("</a>")
            .trim();
        }

        if (url && name) {
          if (!url.startsWith("http")) {
            url = this.source.baseUrl + "/" + url.replace(/^\/+/, "");
          }

          if (imageUrl && !imageUrl.startsWith("http")) {
            imageUrl = this.source.baseUrl + "/" + imageUrl.replace(/^\/+/, "");
          }

          list.push({
            name: name,
            url: url,
            imageUrl: imageUrl,
          });
        }
      }

      return {
        list: list,
        hasNextPage: false,
      };
    } catch (e) {
      return {
        list: [],
        hasNextPage: false,
      };
    }
  }

  async getDetail(url) {
    const client = new Client();

    try {
      const res = await client.get(url);

      if (!res || !res.body) {
        return {
          name: "Unknown",
          description: "",
          author: "",
          genre: [],
          status: 1,
          imageUrl: "",
          chapters: [],
        };
      }

      const html = res.body;

      let title = "";
      let description = "";
      let imageUrl = "";

      // Title
      if (html.includes("<title>")) {
        title = html
          .substringAfter("<title>")
          .substringBefore("</title>")
          .trim();

        title = title
          .replace(" | Towkai", "")
          .replace(" - Towkai", "")
          .trim();
      }

      // Fallback title
      if (!title && html.includes('<h1 style="color:white;">')) {
        title = html
          .substringAfter('<h1 style="color:white;">')
          .substringBefore("</h1>")
          .trim();
      }

      // Meta description
      if (html.includes('<meta name="description"')) {
        description = html
          .substringAfter('<meta name="description"')
          .substringAfter('content="')
          .substringBefore('"')
          .trim();
      }

      // Fallback description
      if (!description && html.includes('<h5 style="color:white;">')) {
        description = html
          .substringAfter('<h5 style="color:white;">')
          .substringBefore("</h5>")
          .replace(/<p>/g, "")
          .replace(/<\/p>/g, "")
          .trim();
      }

      // OG image
      if (html.includes('property="og:image"')) {
        imageUrl = html
          .substringAfter('property="og:image"')
          .substringAfter('content="')
          .substringBefore('"')
          .trim();
      }

      // Fallback image
      if (!imageUrl && html.includes('class="col-md-3 m-t-10"')) {
        imageUrl = html
          .substringAfter('class="col-md-3 m-t-10"')
          .substringAfter('src="')
          .substringBefore('"')
          .trim();
      }

      if (imageUrl && !imageUrl.startsWith("http")) {
        imageUrl =
          this.source.baseUrl + "/" + imageUrl.replace(/^\/+/, "");
      }

      const chapters = [];

      const epBlocks = html
        .split('figure class="figure"')
        .slice(1);

      for (const block of epBlocks) {
        let episodeUrl = "";
        let episodeName = "";

        if (block.includes('<a href="')) {
          episodeUrl = block
            .substringAfter('<a href="')
            .substringBefore('"')
            .trim();
        }

        if (block.includes("<figcaption")) {
          episodeName = block
            .substringAfter("<figcaption")
            .substringAfter(">")
            .substringBefore("</figcaption")
            .trim();
        }

        // Clean malformed/extra HTML
        episodeName = episodeName
          .replace(/<\/?[^>]+>/g, "")
          .trim();

        // Fallback to image alt
        if (!episodeName && block.includes('alt="')) {
          episodeName = block
            .substringAfter('alt="')
            .substringBefore('"')
            .trim();
        }

        if (episodeUrl) {
          if (!episodeUrl.startsWith("http")) {
            episodeUrl =
              this.source.baseUrl + "/" + episodeUrl.replace(/^\/+/, "");
          }

          chapters.push({
            name: episodeName || "Episode",
            url: episodeUrl,
            isFiller: false,
          });
        }
      }

      // Movie page with no episode list
      if (chapters.length === 0) {
        chapters.push({
          name: "Movie",
          url: url,
          isFiller: false,
        });
      } else {
        chapters.reverse();
      }

      return {
        name: title || "Unknown",
        description: description || "",
        author: "",
        genre: [],
        status: 1,
        imageUrl: imageUrl || "",
        chapters: chapters,
      };

    } catch (e) {
      return {
        name: "Unknown",
        description: "",
        author: "",
        genre: [],
        status: 1,
        imageUrl: "",
        chapters: [],
      };
    }
  }

  async getVideoList(url) {
    const client = new Client();

    try {
      if (!url || url === "n/a") {
        return [];
      }

      const res = await client.get(url);

      if (!res || !res.body) {
        return [];
      }

      const html = res.body;

      let videoUrl = "";

      // Normal Towkai player source
      if (html.includes("sources: [{")) {
        videoUrl = html
          .substringAfter("sources: [{")
          .substringAfter("src: '")
          .substringBefore("'")
          .trim();
      }

      // Fallback: find any .m3u8 source
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

      // Fallback: HTML video source
      if (!videoUrl && html.includes("<source")) {
        const sourceParts = html.split("<source");

        for (let i = 1; i < sourceParts.length; i++) {
          if (sourceParts[i].includes('src="')) {
            const candidate = sourceParts[i]
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
      }

      if (!videoUrl) {
        return [];
      }

      return [
        {
          url: videoUrl,
          originalUrl: videoUrl,
          quality: "Auto",
          headers: {
            "Referer": this.source.baseUrl + "/",
            "User-Agent":
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36",
          },
        },
      ];

    } catch (e) {
      return [];
    }
  }

  getHeaders() {
    return {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36",
      "Referer": this.source.baseUrl + "/",
    };
  }

  get supportsLatest() {
    return true;
  }

  async getPageList(url) {
    return [];
  }

  async getHtmlContent(url) {
    return "";
  }

  async cleanHtmlContent(html) {
    return html;
  }

  getFilterList() {
    return [];
  }

  getSourcePreferences() {
    return [];
  }
}

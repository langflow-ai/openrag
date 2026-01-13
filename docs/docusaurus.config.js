// @ts-check
// `@type` JSDoc annotations allow editor autocompletion and type checking
// (when paired with `@ts-check`).
// There are various equivalent ways to declare your Docusaurus config.
// See: https://docusaurus.io/docs/api/docusaurus-config

import {themes as prismThemes} from 'prism-react-renderer';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const isProduction = process.env.NODE_ENV === 'production';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'OpenRAG',
  tagline: 'Open Source RAG Platform',
  favicon: 'img/favicon.ico',

  headTags: [
    ...(isProduction
      ? [
          // Google Consent Mode - Set defaults before Google tags load
          {
            tagName: "script",
            attributes: {},
            innerHTML: `
              window.dataLayer = window.dataLayer || [];
              function gtag(){dataLayer.push(arguments);}

              // Set default consent to denied
              gtag('consent', 'default', {
                'ad_storage': 'denied',
                'ad_user_data': 'denied',
                'ad_personalization': 'denied',
                'analytics_storage': 'denied'
              });
            `,
          },
          // TrustArc Consent Update Listener
          {
            tagName: "script",
            attributes: {},
            innerHTML: `
              (function() {
                function updateGoogleConsent() {
                  if (typeof window.truste !== 'undefined' && window.truste.cma) {
                    var consent = window.truste.cma.callApi('getConsent', window.location.href) || {};

                    // Map TrustArc categories to Google consent types
                    // Category 0 = Required, 1 = Functional, 2 = Advertising, 3 = Analytics
                    var hasAdvertising = consent[2] === 1;
                    var hasAnalytics = consent[3] === 1;

                    gtag('consent', 'update', {
                      'ad_storage': hasAdvertising ? 'granted' : 'denied',
                      'ad_user_data': hasAdvertising ? 'granted' : 'denied',
                      'ad_personalization': hasAdvertising ? 'granted' : 'denied',
                      'analytics_storage': hasAnalytics ? 'granted' : 'denied'
                    });
                  }
                }

                // Listen for consent changes
                if (window.addEventListener) {
                  window.addEventListener('cm_data_subject_consent_changed', updateGoogleConsent);
                  window.addEventListener('cm_consent_preferences_set', updateGoogleConsent);
                }

                // Initial check after TrustArc loads
                if (document.readyState === 'complete') {
                  updateGoogleConsent();
                } else {
                  window.addEventListener('load', updateGoogleConsent);
                }
              })();
            `,
          },
          // IBM Analytics Configuration (required for TrustArc)
          {
            tagName: "script",
            attributes: {},
            innerHTML: `
              window._ibmAnalytics = {
                "settings": {
                  "name": "DataStax",
                  "tealiumProfileName": "ibm-subsidiary",
                },
                "trustarc": {
                  "privacyPolicyLink": "https://ibm.com/privacy"
                }
              };
              window.digitalData = {
                "page": {
                  "pageInfo": {
                    "ibm": {
                      "siteId": "IBM_DataStax",
                    }
                  },
                  "category": {
                    "primaryCategory": "PC230"
                  }
                }
              };
            `,
          },
          // IBM Common Stats Script - loads TrustArc
          {
            tagName: "script",
            attributes: {
              src: "//1.www.s81c.com/common/stats/ibm-common.js",
              async: "true",
            },
          },
        ]
      : []),
  ],

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Set the production url of your site here
  url: 'https://docs.openr.ag',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: process.env.BASE_URL ? process.env.BASE_URL : '/',

  // Control search engine indexing - set to true to prevent indexing
  noIndex: false,

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: 'langflow-ai', // Usually your GitHub org/user name.
  projectName: 'openrag', // Usually your repo name.

  onBrokenLinks: 'throw',
  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: './sidebars.js',
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl:
            'https://github.com/openrag/openrag/tree/main/docs/',
          routeBasePath: '/',
          // Versioning configuration - see VERSIONING_SETUP.md
          // To enable versioning, uncomment the following lines:
          // lastVersion: 'current',
          // versions: {
          //   current: {
          //     label: 'Next (unreleased)',
          //     path: 'next',
          //   },
          // },
          // onlyIncludeVersions: ['current'],
        },
        theme: {
          customCss: './src/css/custom.css',
        },
        // Use preset-classic sitemap https://docusaurus.io/docs/api/plugins/@docusaurus/plugin-sitemap
        sitemap: {
          lastmod: 'date',
          changefreq: 'weekly',
          priority: 0.5,
          ignorePatterns: ['/tags/**'],
          filename: 'sitemap.xml',
          createSitemapItems: async (params) => {
            const {defaultCreateSitemapItems, ...rest} = params;
            const items = await defaultCreateSitemapItems(rest);
            return items.filter((item) => !item.url.includes('/page/'));
          },
        },
      }),
    ],
  ],

  plugins: [require.resolve('docusaurus-plugin-image-zoom')],

  themes: ['@docusaurus/theme-mermaid'],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Replace with your project's social card
      // image: 'img/docusaurus-social-card.jpg',
      navbar: {
        // title: 'OpenRAG',
        logo: {
          alt: 'OpenRAG Logo',
          src: "img/logo-openrag-light.svg",
          srcDark: "img/logo-openrag-dark.svg",
          href: '/',
        },
        items: [
          {
            position: "right",
            href: "https://github.com/langflow-ai/openrag",
            className: "header-github-link",
            target: "_blank",
            rel: null,
            'aria-label': 'GitHub repository',
          },
        ],
      },
      footer: {
        links: [
          {
            title: null,
            items: [
              {
                html: `<div class="footer-links">
                  <span>© ${new Date().getFullYear()} OpenRAG</span>
                  <span id="preferenceCenterContainer"> ·&nbsp; <a href="#" onclick="if(typeof window !== 'undefined' && window.truste && window.truste.eu && window.truste.eu.clickListener) { window.truste.eu.clickListener(); } return false;" style="cursor: pointer;">Manage Privacy Choices</a></span>
                  </div>`,
              },
            ],
          },
        ],
      },
      algolia: {
        appId: "SMEA51Q5OL",
        // public key, safe to commit
        apiKey: "b2ec302e9880e8979ad6a68f0c36271e",
        indexName: "openrag-algolia",
        contextualSearch: true,
        searchParameters: {},
        searchPagePath: "search",
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        additionalLanguages: ['bash', 'docker', 'yaml'],
      },
      mermaid: {
        theme: {light: 'neutral', dark: 'forest'},
        options: {
          maxTextSize: 50000,
          fontSize: 18,
          fontFamily: 'Arial, sans-serif',
          useMaxWidth: false,
          width: '100%',
          height: 'auto',
        },
      },
      zoom: {
        selector: '.markdown img',
        background: {
          light: 'rgb(255, 255, 255)',
          dark: 'rgb(50, 50, 50)',
        },
        config: {
          margin: 24,
          scrollOffset: 0,
        },
      },
    }),
};

export default config;

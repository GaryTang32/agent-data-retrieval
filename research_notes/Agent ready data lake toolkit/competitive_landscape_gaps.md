# Competitive Landscape and Unmet Gaps: Toolkits That Turn Unstructured Documents and Tools into an Agent-Retrievable Data Lake (as of Nov 2026)

Method note: GitHub stars, last-push dates and latest releases were pulled on 2026-11-06 from the public GitHub mirror API `ungh.cc` (the direct GitHub API was blocked in this session). License terms were read from each repo's raw `LICENSE` file on `raw.githubusercontent.com` on the same day. Each repo row cites its GitHub URL. Star counts are a point-in-time snapshot. Commercial-product facts come from vendor docs and blogs and are labeled **[vendor claim]** where they cannot be checked independently.

## Open-source RAG/knowledge platforms: scope, license, activity, architecture

### Takeaway
The open-source field is crowded and very active. It splits into (a) end-user "RAG app" platforms (RAGFlow, Dify, AnythingLLM, Onyx, Open WebUI, Kotaemon), (b) developer frameworks (LlamaIndex, Haystack, txtai), (c) graph/memory engines (GraphRAG, LightRAG, Graphiti, Cognee, Mem0, KAG, HippoRAG), and (d) parsers (Docling, MinerU, Marker, MarkItDown, Unstructured). None of them defines an open, engine-neutral data format that covers parsed docs, tables, graph, vectors, tool records, ACLs and lineage together. Several of the most popular ones use non-OSI or "open core" licenses (Dify, Onyx EE, Open WebUI, MinerU), which leaves room for a permissively licensed alternative.

### Cited Findings

**Activity snapshot (stars / last push / latest release, 2026-11-06)**
- RAGFlow: 93,668 stars; pushed 2026-11-06; v1.0.0-rc3 (2026-10-30). Its repo now describes itself as "an agent-native database: a RAG engine that grew into context infrastructure". Apache-2.0. — [GitHub infiniflow/ragflow](https://github.com/infiniflow/ragflow)
- Dify: 160,493 stars; release 1.19.0 (2026-11-04). The license is a "modified version of the Apache License 2.0" that bans running a multi-tenant service without written permission and bans removing the logo or copyright from the frontend, so it is not OSI open source. — [GitHub langgenius/dify LICENSE](https://github.com/langgenius/dify/blob/main/LICENSE)
- LlamaIndex: 52,826 stars; v0.14.25 (2026-09-21); MIT. The repo tagline is now "the document processing platform for AI", which shows a pivot toward parsing/LlamaCloud. — [GitHub run-llama/llama_index](https://github.com/run-llama/llama_index)
- Haystack: 26,935 stars; v3.4.1 (2026-10-21); Apache-2.0. Tagline: "AI orchestration framework for building context-engineered ... LLM applications". — [GitHub deepset-ai/haystack](https://github.com/deepset-ai/haystack)
- Kotaemon: 25,853 stars; last push 2026-07-14; v0.12.0 (2026-05-31). Activity is slowing. License file was not retrieved (see Gaps). — [GitHub Cinnamon/kotaemon](https://github.com/Cinnamon/kotaemon)
- R2R (SciPhi): 8,063 stars; last push 2025-11-07; last release v3.6.5 (2025-06-06); MIT. **It appears dormant for about a year.** — [GitHub SciPhi-AI/R2R](https://github.com/SciPhi-AI/R2R)
- Onyx (formerly Danswer): 33,235 stars; v5.1.0 (2026-11-06). License: code under `ee` directories falls under the "Onyx Enterprise License", the rest is MIT (open core). — [GitHub onyx-dot-app/onyx](https://github.com/onyx-dot-app/onyx)
- AnythingLLM: 67,981 stars; v1.19.0 (2026-10-26); MIT. Positioned as "local-first". — [GitHub Mintplex-Labs/anything-llm](https://github.com/Mintplex-Labs/anything-llm)
- Open WebUI: 157,843 stars; v0.13.0 (2026-11-03). It uses a custom "Open WebUI License" (BSD-style with extra conditions). — [GitHub open-webui/open-webui](https://github.com/open-webui/open-webui)
- Cognee: 33,093 stars; v1.6.6 (2026-10-29); Apache-2.0. Repositioned as an "AI memory platform for agents". — [GitHub topoteretes/cognee](https://github.com/topoteretes/cognee)
- Graphiti (Zep): 32,560 stars; v0.31.2 (2026-10-20); Apache-2.0. Builds "real-time knowledge graphs for AI agents" (temporal, incremental). — [GitHub getzep/graphiti](https://github.com/getzep/graphiti)
- Microsoft GraphRAG: 36,577 stars; v3.3.0 (2026-10-08); MIT. — [GitHub microsoft/graphrag](https://github.com/microsoft/graphrag)
- LightRAG: 40,549 stars; v1.5.7 (2026-09-02); MIT. — [GitHub HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)
- RAG-Anything (HKUDS, multimodal layer on top of LightRAG): 24,436 stars; v1.4.4 (2026-10-28); MIT. — [GitHub HKUDS/RAG-Anything](https://github.com/HKUDS/RAG-Anything)
- txtai: 13,065 stars; v9.14.0 (2026-10-06); Apache-2.0. — [GitHub neuml/txtai](https://github.com/neuml/txtai)
- Mem0: 68,503 stars; Apache-2.0. A "memory layer for AI agents". — [GitHub mem0ai/mem0](https://github.com/mem0ai/mem0)
- KAG (OpenSPG/Ant Group): 9,151 stars; last push 2026-01-28; last release v0.8.0 (2025-06-28); Apache-2.0. Slowing. — [GitHub OpenSPG/KAG](https://github.com/OpenSPG/KAG)
- HippoRAG: 4,100 stars; v1.0.0 (2025-02); research code. — [GitHub OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG)
- fast-graphrag (Circlemind): 3,969 stars; last push 2025-11-01, which suggests it is dormant. — [GitHub circlemind-ai/fast-graphrag](https://github.com/circlemind-ai/fast-graphrag)
- Pathway llm-app ("keeps answers in sync with your documents", streaming/incremental): 58,727 stars; MIT. — [GitHub pathwaycom/llm-app](https://github.com/pathwaycom/llm-app)
- neo4j-graphrag-python: 1,329 stars; 1.23.0 (2026-10-28). FalkorDB GraphRAG-SDK: 1,028 stars; v1.5.0 (2026-10-22). — [GitHub neo4j/neo4j-graphrag-python](https://github.com/neo4j/neo4j-graphrag-python); [GitHub FalkorDB/GraphRAG-SDK](https://github.com/FalkorDB/GraphRAG-SDK)
- LanceDB (embedded multimodal retrieval/storage format): 11,851 stars; v0.41.0 (2026-10-29). — [GitHub lancedb/lancedb](https://github.com/lancedb/lancedb)
- Open catalogs: Unity Catalog OSS ("Open, Multi-modal Catalog for Data & AI") has 3,568 stars, v0.7.0 (2026-10-13). Apache Gravitino has 3,346 stars, v1.3.1. — [GitHub unitycatalog/unitycatalog](https://github.com/unitycatalog/unitycatalog); [GitHub apache/gravitino](https://github.com/apache/gravitino)

**Open-source parsers (relevant as ingestion front ends)**
- MarkItDown (Microsoft): 194,127 stars; v0.1.9 (2026-10-21). This is the largest star count in the space for a simple "files to Markdown" converter. — [GitHub microsoft/markitdown](https://github.com/microsoft/markitdown)
- Docling (IBM/LF AI): 70,203 stars; v2.148.0 (2026-11-05), so releases are very frequent; MIT. — [GitHub docling-project/docling](https://github.com/docling-project/docling)
- MinerU: 83,186 stars; 4.1.7 (2026-11-04). The "MinerU Open Source License" is Apache-2.0 plus extra terms that require a commercial license above 100M MAU or USD 20M monthly revenue. — [GitHub opendatalab/MinerU LICENSE](https://github.com/opendatalab/MinerU/blob/master/LICENSE)
- Marker (Datalab): 40,787 stars; v2.1.0 (2026-10-29). The repo LICENSE file now reads Apache-2.0. Earlier versions were GPL-3.0 with restricted model weights, and model-weight terms may still differ (not verified). — [GitHub datalab-to/marker](https://github.com/datalab-to/marker)
- Unstructured (OSS library): 15,680 stars; 0.27.36 (2026-10-30); Apache-2.0. — [GitHub Unstructured-IO/unstructured](https://github.com/Unstructured-IO/unstructured)
- Sycamore (Aryn): 605 stars; last push 2026-08-01; Apache-2.0. It stays Apache-2.0 after Glean bought Aryn. — [GitHub aryn-ai/sycamore](https://github.com/aryn-ai/sycamore); [Aryn joins Glean](https://www.aryn.ai/post/aryn-transition)
- Instill Core: 2,321 stars; last release v0.58.1 (2025-10-14), last push 2026-06. Slowing. — [GitHub instill-ai/instill-core](https://github.com/instill-ai/instill-core)

**Architecture and positioning signals**
- Microsoft's GraphRAG README warns that "GraphRAG indexing can be an expensive operation" and advises users to "start small". GraphRAG 1.0 added an update command that computes deltas against an existing index and reuses an LLM cache. — [DEV Community comparison quoting README](https://dev.to/jangwook_kim_e31e7291ad98/lightrag-vs-microsoft-graphrag-in-2026-the-costs-we-could-verify-and-the-benchmark-numbers-we-5bci)
- LightRAG skips community reports, so builds and incremental updates are cheaper, but its entity-extraction cost is about the same as GraphRAG's. — [DEV Community](https://dev.to/jangwook_kim_e31e7291ad98/lightrag-vs-microsoft-graphrag-in-2026-the-costs-we-could-verify-and-the-benchmark-numbers-we-5bci); [GitHub HKUDS/LightRAG](https://github.com/hkuds/lightrag)

### Inferences
- Projects are converging on the same terms: "context infrastructure" (RAGFlow), "context-engineered" (Haystack), "memory platform" (Cognee, Mem0), "document processing platform" (LlamaIndex). A new toolkit needs a sharper anchor than "RAG engine". "Open data format + compiler for agent context" is one candidate.
- License friction is real at the top of the market. Dify (multi-tenant ban), Onyx (EE carve-outs), Open WebUI (custom license) and MinerU (revenue thresholds) are all non-pure-permissive. An Apache-2.0/MIT toolkit with no enterprise carve-outs is a distinguishing point for vendors and SaaS builders who want to embed it.
- Several earlier contenders (R2R, fast-graphrag, KAG, Instill, Kotaemon) have slowed or stalled. Long-term maintenance is part of what users are buying.

### Gaps
- Kotaemon, Graphiti and Cognee releases were checked but not their governance. Kotaemon's license file could not be fetched (it is believed to be Apache-2.0, not verified).
- Not checked this session: Tensorlake/Indexify repo (the ungh lookup returned empty, so the repo may have been renamed), LlamaCloud pricing, Haystack Enterprise, Weaviate/Qdrant/Milvus as competitors, and Kernel Memory.

## Commercial platforms: scope and positioning

### Takeaway
Hyperscalers and data platforms now ship managed "knowledge base for agents" products. These include Azure Foundry IQ (agentic retrieval exposed over MCP), Databricks Agent Bricks plus `ai_parse_document` on Unity Catalog, Snowflake `AI_PARSE_DOCUMENT` (agentic mode preview Oct 2026) plus Cortex Search/Agents, and AWS Bedrock Knowledge Bases with GraphRAG on Neptune Analytics. Each is strong inside its own cloud or lakehouse, but data, graph and indexes stay locked to that platform. Glean is consolidating parsing (it bought Aryn). Contextual AI lost its CEO and researchers to Google DeepMind.

### Cited Findings
- **Azure Foundry IQ**: reusable knowledge bases built on Azure AI Search agentic retrieval. An LLM planner breaks questions into subqueries, runs them in parallel, reranks semantically and returns unified results. Sources include SharePoint, OneLake, Blob, AI Search indexes, the web, and MCP servers (MCP sources reportedly in private preview). Agents connect through an MCP endpoint (`knowledge_base_retrieve`). API versions are still `*-preview` (e.g. 2026-08-01-preview). — [What is Foundry IQ (Microsoft Learn)](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-foundry-iq); [Connect agents to Foundry IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect); [Foundry IQ FAQ](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/foundry-iq-faq)
- Foundry IQ "boost[s] response relevance by 36% with agentic retrieval" **[vendor claim]**. — [Microsoft Tech Community](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/foundry-iq-boost-response-relevance-by-36-with-agentic-retrieval/4470720)
- Foundry IQ bills twice: Azure AI Search tokens for retrieval, plus Azure OpenAI for query planning and synthesis. — [Spyglass MTG blog](https://www.spyglassmtg.com/blog/unifying-retrieval-for-ai-agents-with-azure-ai-search-and-foundry-iq)
- **Databricks**: `ai_parse_document` is a SQL function plus REST API that produces a "bronze layer" of text, tables and figure descriptions. `ai_prep_search` (Beta) turns parsed docs into semantic chunks for indexing. Agent Bricks Knowledge Assistant is document Q&A pointed at a Unity Catalog Volume. — [Databricks docs: Intelligent document processing](https://docs.databricks.com/gcp/en/agents/agent-bricks/intelligent-document-processing); [Databricks community blog](https://community.databricks.com/t5/technical-blog/combining-agent-bricks-and-ai-parse-document-for-smarter/ba-p/143801)
- Databricks' own framing: "PDF parsing for agentic AI is still unsolved", which it uses to pitch one function that replaces multi-service pipelines. — [VentureBeat](https://venturebeat.com/data/databricks-pdf-parsing-for-agentic-ai-is-still-unsolved-new-tool-replaces); [InfoWorld](https://www.infoworld.com/article/4089186/databricks-fires-back-at-snowflake-with-sql-based-ai-document-parsing.html)
- Supported formats at launch were limited (PDF, images, DOC/DOCX, PPT/PPTX), and Agent Bricks status was reported as Beta by a partner guide (may have changed). — [Databricks blog](https://www.databricks.com/blog/pdfs-production-announcing-state-art-document-intelligence-databricks); [LatentView guide](https://www.latentview.com/blog/document-intelligence-on-databricks-2025-2026-what-to-use-when-and-why/)
- **Snowflake**: `AI_PARSE_DOCUMENT` added an AGENTIC mode in Public Preview on 2026-10-28 for charts, diagrams and tables via a single SQL call. Image extraction went GA and the page limit rose to 2,000 pages on 2026-04-30. — [Snowflake release note Oct 28 2026](https://docs.snowflake.com/en/release-notes/2026/other/2026-10-28-ai-parse-document-agentic-mode-preview); [Apr 30 2026 image extraction GA](https://docs.snowflake.com/en/release-notes/2026/other/2026-04-30-ai-parse-document-image-extraction-ga); [Apr 30 2026 2,000 pages](https://docs.snowflake.com/en/release-notes/2026/other/2026-04-30-ai-parse-document-2000-pages)
- LandingAI announced a January 2026 Snowflake partnership for ADE (aggregator report). — [Tracxn / search summary](https://tracxn.com/d/companies/landing-ai/__PeMXn6V7ihfr6AhJJIEUX-ka2BCAP-B4a-FlYincI1E)
- **AWS Bedrock Knowledge Bases GraphRAG** (Neptune Analytics): AWS docs list these limits: no autoscaling for Neptune Analytics graphs; GraphRAG only supports S3 as a data source; the KB must be deleted before the graph; 1,000 files per data source by default (10,000 on request). — [AWS docs: Build a knowledge base with graphs](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-build-graphs.html)
- Third-party claims about Bedrock GraphRAG (less authoritative): only semantic search for the Neptune Analytics configuration; openCypher only; no scale-to-zero (about $0.48/hr per memory-optimized unit in examples); orphaned graphs after KB deletion; no built-in reasoner. — [Atlan: Neptune use cases/limits](https://atlan.com/know/ai-agent/knowledge-graph/amazon-neptune-graph-database/); [BigData Boutique](https://bigdataboutique.com/blog/aws-vector-database-options)
- **AWS Bedrock AgentCore Gateway** turns OpenAPI, Smithy and Lambda targets into MCP tools and offers semantic tool search. — [QueryNow comparison](https://www.querynow.com/ai-agents/mcp/mcp-gateways-and-registries)
- **Glean** bought Aryn (DocParse/Sycamore) on 2026-03-11. The Aryn cloud service shut down on 2026-04-15, and Sycamore stays Apache-2.0. This is reported as Glean's first acquisition, aimed at deeper unstructured-document parsing for Glean Assistant and Agents. — [Aryn joins Glean](https://www.aryn.ai/post/aryn-transition); [stockanalysis.com Glean profile](https://stockanalysis.com/private/glean/)
- **Contextual AI**: in May 2026, CEO Douwe Kiela and more than 20 researchers joined Google DeepMind under a licensing agreement, and Jay Chen became interim CEO (single Wikipedia source, not confirmed against primary news). The product shipped "Agent Composer" in public preview on 2026-01-27. — [Wikipedia: Contextual AI](https://en.wikipedia.org/wiki/Contextual_AI); [Contextual AI 2026 release notes](https://docs.contextual.ai/release-notes/2026)

### Inferences
- Every hyperscaler and lakehouse now has parse, index, agentic retrieve and MCP built in. The strongest open-source position is portability across them: the same parsed artifacts, graph and tool records should be loadable into Azure AI Search, Databricks/Unity Catalog, Snowflake, Bedrock or a local stack. Competing on managed convenience inside one cloud would not work.
- AWS GraphRAG's "S3 only, openCypher only, always-on graph" constraints and Foundry IQ's preview status suggest managed graph RAG is still immature. A portable graph layer (e.g. property-graph export to Neo4j, FalkorDB, Neptune or Kuzu-like embedded stores) has room.
- Consolidation (Glean buying Aryn, the Contextual AI and Google deal, Rossum reportedly bought by Coupa) shows that buyer lock-in risk is real. That supports an "open format so your data lake survives vendor churn" message.

### Gaps
- Not verified this session: Google Vertex AI Search / Gemini Enterprise (formerly Agentspace) current data-store and connector scope; Palantir Ontology/AIP (ontology "actions" as typed tools is a close conceptual analogue to "tools as data"); Neo4j AuraDB GraphRAG/Aura Agent products; Box AI; Vectara 2026 status; Snowflake Cortex Knowledge Extensions and Snowflake Intelligence 2026 details; Glean pricing. Background knowledge (pre-2026, not re-verified): Palantir models business objects plus "Actions/Functions" in one ontology that agents use, which is the nearest commercial precedent for tools and data in one semantic layer, but it is proprietary and platform-bound.

## Unstructured-data ETL / document parsing vendors

### Takeaway
Parsing is a well-funded, consolidating category (Reducto raised about $108M total; LandingAI ADE ties into Snowflake; Glean bought Aryn). Hyperscalers are absorbing parsing as SQL functions. Open-source parsers (Docling, MinerU, Marker, MarkItDown) have huge adoption. A new toolkit should not build its own parser. It should orchestrate pluggable parsers into a common, provenance-preserving schema.

### Cited Findings
- Reducto: $75M Series B led by a16z (Oct 2025) after an April 2025 Series A. About $108M total per aggregators. A $600M valuation is cited by one vendor profile (uncorroborated). — [PR Newswire: Reducto Series B](https://www.prnewswire.com/news-releases/reducto-raises-75m-series-b-to-define-the-future-of-ai-document-intelligence-302581462.html); [IDP-Software Reducto profile](https://idp-software.com/vendors/reducto-ai/)
- Extend about $17M raised; Datalab about $3.5M seed (Marker is its OSS); Tensorlake funding undisclosed, described as a document ingestion API. Rossum was reportedly acquired by Coupa in May 2026, and LandingAI ADE Gen2 reportedly cut per-page prices in Sept 2026 (newsletter roundup; unverified). — [The Sunday Underwrite: Document AI](https://asitsahoo.substack.com/p/document-ai)
- LandingAI funding: about $57M over four rounds per one profile, while another says it is undisclosed (conflict). — [Tracxn](https://tracxn.com/d/companies/landing-ai/__PeMXn6V7ihfr6AhJJIEUX-ka2BCAP-B4a-FlYincI1E); [IDP-Software LandingAI](https://idp-software.com/vendors/landing-ai/)
- Unstructured.io's 2026 news is government/security-led: IL5 Authority to Operate (Feb 2026, on top of FedRAMP High), a $2M AFWERX award, Azure integration expansion (June), and an "Unstructured Transform MCP" launch (July 2026). — [BusinessWire: Unstructured IL5 ATO](https://www.businesswire.com/news/home/20260204238090/en/Unstructured-Achieves-IL5-Authority-to-Operate); [Unstructured blog](https://unstructured.io/blog)
- Aryn's DocParse cloud is shut down after the Glean acquisition (service transition page). — [Aryn service transition](https://app.aryn.ai/service-transition)
- Comparison roundups for 2026 (Firecrawl, Vstorm) rank parsing services for RAG, but they are vendor-authored. — [Firecrawl: structured extraction tools 2026](https://www.firecrawl.dev/blog/best-structured-data-extraction-tools); [Vstorm: top 10 parsing services 2026](https://vstorm.co/llamaindex/top-10-document-parsing-services-for-rag-pipelines-and-llm-applications/)

### Inferences
- The parser market is turning into a commodity at the API level, with differentiation moving to accuracy on hard layouts, price per page and compliance (FedRAMP/IL5). An open toolkit's value is a normalized intermediate representation (elements, bounding boxes, reading order, tables as typed tables, figures, page-level provenance). That lets users swap Docling, MinerU, Reducto, LandingAI or Snowflake AGENTIC mode without re-engineering downstream graph and schema steps.
- Docling's MIT license and very fast release cadence (v2.148) make it the most natural default parser dependency. MinerU's revenue thresholds and Marker's historical weight restrictions argue for keeping them as optional plugins.

### Gaps
- No verified 2026 funding or pricing data for Extend, Datalab, Tensorlake, Instill or Vectorize. No data found on whether Vectorize was acquired (the search returned irrelevant SPAC results). No current Unstructured.io platform pricing found.

## MCP gateways, registries, tool catalogs: does anyone treat tools as data alongside documents?

### Takeaway
Tool catalogs are moving toward "tools as retrievable records". Gateways now index tool schemas and use hybrid BM25 + vector search (SCOUT/PayPal, the agentic-community MCP Gateway & Registry, AWS AgentCore Gateway, Composio "tool search"). But they keep tools in a separate gateway catalog, not in the same graph and catalog as documents and their entities. Foundry IQ comes closest by treating MCP servers as a knowledge source. No open project found models tools, docs, entities, permissions and lineage in one graph and schema.

### Cited Findings
- SCOUT (arXiv 2608.23992) exposes a `tool_search` meta-tool that fuses BM25 and dense retrieval via Reciprocal Rank Fusion. In a production deployment at PayPal it cut tool-token use by about 99% **[self-reported]**. — [arXiv 2608.23992](https://arxiv.org/abs/2608.23992)
- The MCP Gateway & Registry (agentic-community, promoted on the AWS Open Source blog) does dynamic tool discovery with hybrid search over tool embeddings and positions itself for governance of "AI assets". — [AWS Open Source Blog](https://aws.amazon.com/blogs/opensource/governing-ai-assets-at-scale-with-mcp-gateway-and-registry/); [Dynamic tool discovery docs](https://agentic-community.github.io/mcp-gateway-registry/dynamic-tool-discovery/)
- Gateways bundle audit trails, rate limiting and per-call policy. Google and AWS have both added per-call policy controls. — [QueryNow](https://www.querynow.com/ai-agents/mcp/mcp-gateways-and-registries); [Medium: MCP tool discovery problem](https://medium.com/@amiarora/solving-the-mcp-tool-discovery-problem-how-ai-agents-find-what-they-need-b828dbce2c30)
- At least 15 MCP registry products exist in 2026 (vendor comparison). — [MintMCP: 15 MCP registry tools](https://www.mintmcp.com/blog/mcp-registry-tools)
- Open-source activity: Composio has 30,936 stars, MIT, and markets "1000+ toolkits, tool search, context management, authentication". The official MCP registry has 7,445 stars, v1.8.7 (2026-10-30). IBM ContextForge ("AI gateway, registry, and proxy ... MCP, A2A, REST/gRPC") has 4,756 stars, v1.1.0. agentgateway has 5,944 stars, v1.7.0. docker/mcp-gateway has 1,626 stars. — [GitHub ComposioHQ/composio](https://github.com/ComposioHQ/composio); [GitHub modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry); [GitHub IBM/mcp-context-forge](https://github.com/IBM/mcp-context-forge); [GitHub agentgateway/agentgateway](https://github.com/agentgateway/agentgateway); [GitHub docker/mcp-gateway](https://github.com/docker/mcp-gateway)
- Foundry IQ knowledge bases can include MCP servers as a knowledge source alongside SharePoint and OneLake, though this is preview. — [Microsoft Learn: What is Foundry IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-foundry-iq)
- Unity Catalog OSS describes itself as a "multi-modal catalog for data & AI". Background (not re-verified this session): it registers functions alongside tables, which makes functions usable as agent tools. That is the closest open precedent to tools-as-catalog-objects next to data. — [GitHub unitycatalog/unitycatalog](https://github.com/unitycatalog/unitycatalog)

### Inferences
- The white space is a unified record model: a `ToolRecord` (schema, auth scope, side effects, cost/latency, owner, version, provenance) stored in the same catalog and graph as `Document`, `Chunk`, `Table` and `Entity` nodes, with edges such as "tool X reads/writes entity type Y" and "doc Z documents tool X". Retrieval could then return mixed evidence: a fact and the tool that can verify or act on it. Gateways handle runtime policy, catalogs handle data. Nobody found joins them in an open format.
- Integrating rather than competing with gateways (agentgateway, ContextForge, Docker MCP, Composio) is likely wiser: ingest their registries into the lake and emit `tool_search` results back to them.

### Gaps
- Not checked: Kong AI Gateway MCP features, Cloudflare MCP server portals, Smithery, Glama, and whether Composio's "tool search" indexes tool docs jointly with user data. No source confirms any product that models tools and documents in one knowledge graph. That absence comes from my searches, not from a definitive survey.

## User complaints (parsing, graph indexing cost, lock-in, ACLs, incremental updates, eval, provenance)

### Takeaway
Recurring pain points, in roughly descending order of evidence: (1) graph indexing token cost and poor incremental updates; (2) parsing quality on complex PDFs (vendors admit it is "unsolved"); (3) permission and ACL sync correctness; (4) citation and provenance loss and lack of validation; (5) lock-in and service shutdowns. This session found no HN or Reddit threads; the evidence is mostly practitioner blogs, papers and vendor posts.

### Cited Findings
- Graph indexing cost: a 2026 arXiv paper reports LightRAG using more than 757M tokens on HotpotQA vs 62M for naive RAG, which makes it "impractical for dynamic or large-scale knowledge bases where frequent updates are required". — [arXiv: LiteRAG / M-RAG 2026 papers](https://arxiv.org/pdf/2609.10239); [arXiv 2603.26667](https://arxiv.org/pdf/2603.26667)
- Blog estimates put GraphRAG indexing at roughly 1,000x vector RAG, and LightRAG at roughly 1/10 to 1/5 of GraphRAG (conflicts with the arXiv finding above, figures vary widely). — [beri.net](https://www.beri.net/article/graphrag-vs-vector-rag-indexing-query-cost-lightrag-lazygraphrag-2026); [bestaiweb: "$33K cost cliff"](https://www.bestaiweb.ai/indexing-cost-token-blowup-and-the-hard-engineering-limits-of-graphrag-at-scale/)
- Community structure in GraphRAG reportedly must be regenerated on updates, which drives up the cost of incremental indexing. — [DEV Community](https://dev.to/jangwook_kim_e31e7291ad98/lightrag-vs-microsoft-graphrag-in-2026-the-costs-we-could-verify-and-the-benchmark-numbers-we-5bci)
- Parsing quality: Databricks itself says "PDF parsing for agentic AI is still unsolved". — [VentureBeat](https://venturebeat.com/data/databricks-pdf-parsing-for-agentic-ai-is-still-unsolved-new-tool-replaces)
- ACLs: "incremental sync of permissions is significantly harder than incremental sync of content". Filtering is only as trustworthy as the last ACL sync, and some platforms enforce permissions only at the chat-UI layer, which can leak content. — [Truto: document-level RBAC for RAG](https://truto.one/blog/how-to-maintain-document-level-rbac-in-enterprise-rag-pipelines/)
- A 2026 arXiv paper on production RAG says access-control bugs in application-layer filter logic are among the most severe and hardest-to-detect failures (the paper also promotes its own pgvector-based unified layer). — [arXiv 2605.03275](https://arxiv.org/pdf/2605.03275)
- Provenance: guides recommend attaching source path, author, timestamp and version to every element and chunk. Many production systems "silently fail to validate" citations, and aggressive summarization loses citations. — [Barking Iguana: citations-required RAG over 50K docs](https://barkingiguana.com/writing/how-to-build-a-citations-required-rag-over-50k-internal-documents/); [Prompt20: RAG in production](https://blog.prompt20.com/posts/rag-production-architecture/); [Unstructured: RAG pipeline challenges](https://unstructured.io/insights/rag-pipeline-challenges-from-data-ingestion-to-retrieval)
- Incremental change detection: use last-modified timestamps when reliable, else content hashing. — [Prompt20](https://blog.prompt20.com/posts/rag-production-architecture/)
- Lock-in and churn: Aryn's DocParse shut down within about 5 weeks of the Glean acquisition announcement. — [Aryn joins Glean](https://www.aryn.ai/post/aryn-transition)
- Tool-context bloat: full tool schemas fill the context window before the query arrives. — [arXiv 2608.23992](https://arxiv.org/abs/2608.23992)

### Inferences
- The top complaints map directly to toolkit features. Cost-aware, incremental graph construction (entity-level deltas, no global community recompute, budgets and caching). Pluggable parsers with per-element confidence and page/bbox provenance. ACLs as first-class, versioned edges synced from sources and enforced at retrieval. Lineage from answer to chunk to element to page to source version. Tool records retrieved under the same permission model.
- Evaluation and debugging complaints are likely real but were not evidenced in this session's sources (see Gaps).

### Gaps
- No Hacker News or Reddit threads were surfaced by search, so community sentiment for specific products (RAGFlow, Dify, Onyx GitHub issues) is unverified. A follow-up should mine GitHub issues with labels like "bug", "performance" and "permission" on ragflow, dify, graphrag and LightRAG.
- No sourced evidence was gathered on evaluation/debugging tooling complaints or on schema-drift complaints.

## Gaps and positioning for an open, permissively licensed, composable toolkit

### Takeaway
The most defensible spot is an open specification plus reference implementation for the "agent data lake" layer. Concretely, a typed, versioned schema and format covering parsed elements, tables, entities/relations, embeddings, tool records, ACLs and lineage, stored on open table/file formats. It would come with pluggable parsers and graph builders and exporters to every major retrieval backend and MCP. Adoption depends on piggybacking on existing ecosystems (Docling, LlamaIndex/Haystack, MCP, Lance/Iceberg/Unity Catalog), keeping incremental graph costs low, and a clean Apache-2.0 license. It also needs to avoid becoming "yet another RAG chat app".

### Cited Findings
- Incumbents are heading the same way, which validates demand: RAGFlow rebrands as "agent-native database / context infrastructure", Unity Catalog OSS as a "multi-modal catalog for data & AI", and Foundry IQ unifies knowledge sources, including MCP, behind one retrieval endpoint. — [GitHub infiniflow/ragflow](https://github.com/infiniflow/ragflow); [GitHub unitycatalog/unitycatalog](https://github.com/unitycatalog/unitycatalog); [Microsoft Learn: Foundry IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-foundry-iq)
- Lakehouse vendors frame parsing output as a "bronze layer" in SQL, which shows that buyers want document outputs as governed tables. — [Databricks docs](https://docs.databricks.com/gcp/en/agents/agent-bricks/intelligent-document-processing)
- Data-catalog vendors (Atlan) argue that Bedrock KBs and Neptune lack a governed "context layer" or catalog. That is a vendor viewpoint, but it shows the governance gap is being marketed. — [Atlan: Bedrock KBs vs external data catalog](https://atlan.com/know/ai-agent/aws/amazon-bedrock-knowledge-bases-vs-external-data-catalog/); [Atlan: Neptune vs KG context layer](https://atlan.com/know/ai-agent/knowledge-graph/amazon-neptune-vs-knowledge-graph-context-layer/)
- Permissive-license gap: Dify (multi-tenant restriction), Onyx (EE directories), MinerU (revenue/MAU thresholds) and Open WebUI (custom license) are all non-pure-permissive. — [Dify LICENSE](https://github.com/langgenius/dify/blob/main/LICENSE); [GitHub onyx-dot-app/onyx](https://github.com/onyx-dot-app/onyx); [MinerU LICENSE](https://github.com/opendatalab/MinerU/blob/master/LICENSE); [GitHub open-webui/open-webui](https://github.com/open-webui/open-webui)

### Inferences
**Concrete gaps a new toolkit could fill (ranked by evidence strength):**
1. **Open, engine-neutral intermediate format** for parsed docs, tables, graph, vectors, tool records, ACLs and lineage. None was found among the surveyed projects. Each stores its own internal state (RAGFlow's DB, GraphRAG parquet, LightRAG KV/graph stores, Graphiti in Neo4j). Building on Lance/Parquet/Iceberg plus a JSON-Schema/Pydantic spec would make outputs portable to Databricks, Snowflake, Azure AI Search, Bedrock, Neo4j and local stores.
2. **Cost-bounded incremental graph engineering**: entity-level deltas, schema-guided extraction (ontology/"data schema engineering" before extraction to cut tokens), token budgets, and caching. This directly targets the top complaint about GraphRAG and LightRAG.
3. **Tools as first-class data**: tool records (from MCP registries, OpenAPI, functions) live in the same graph as documents and entities, with relations, permissions and provenance, and joint retrieval of "evidence + actionable tool". Gateways do separate tool search only.
4. **Permissions and lineage as data, not app logic**: ACL edges synced and versioned per source, enforced at retrieval, and every answer traceable to element, page and source version. Evidence shows this is a top failure mode and that many platforms enforce it only in the UI.
5. **Parser-agnostic ingestion with quality signals**: wrap Docling, MinerU, Marker, MarkItDown, Unstructured, Reducto, LandingAI and the cloud SQL parsers behind one element schema with per-element confidence, so users can route hard pages to costly parsers.
6. **Evaluation and debugging over the lake** (graph and retrieval diffing across versions, citation validation). Demand is inferred; this session gathered weak evidence.

**What makes adoption likely:**
- Apache-2.0 with no EE carve-out. Python-first library plus CLI. Works embedded (no server) and scales out. Integrates as a LlamaIndex/Haystack component and an MCP server rather than competing with them. Defaults to Docling plus a local embedded store for a "pip install to first lake in 5 minutes" experience. Exporters to the hyperscaler KBs so enterprises can adopt it without leaving their cloud.

**What makes adoption unlikely:**
- Building yet another chat UI or RAG app (the space is saturated: Dify 160k, Open WebUI 158k, RAGFlow 94k, AnythingLLM 68k stars). Requiring a heavy server stack. Graph construction that costs as much as GraphRAG. Specs without reference connectors. Hyperscalers bundling "good enough" parse, retrieve and MCP inside existing contracts (Foundry IQ, Agent Bricks, Snowflake AGENTIC mode). Maintainer burnout, as seen with stalled projects (R2R, fast-graphrag, KAG).

### Gaps
- No market-size or buyer-survey data was found on demand for an "open agent data format". The positioning inferences rest on product-direction signals and complaint patterns, not on demand measurement.
- Unchecked: whether any emerging standard (e.g. an MCP resources/knowledge extension, OpenLineage for AI, Lance namespace specs, or a Linux Foundation effort) already targets a unified doc+graph+tool format. This should be verified before claiming "no standard exists".

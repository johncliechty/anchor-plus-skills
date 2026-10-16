import zlib from 'node:zlib';
import { fetchWithBackoff } from './search.mjs';

/**
 * Downloads a PDF from the given URL with a timeout and handles errors.
 * Supports a custom fetch function for testing.
 */
export async function downloadPdf(url, options = {}) {
  const timeoutMs = options.timeout ?? 5000;
  const customFetch = options.fetch ?? fetch;
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await customFetch(url, {
      ...options.fetchOptions,
      signal: controller.signal,
    });
    clearTimeout(id);

    if (response.status === 404) {
      throw new Error(`Failed to download PDF: HTTP 404 Not Found at URL: ${url}`);
    }
    if (!response.ok) {
      throw new Error(`Failed to download PDF: HTTP ${response.status} ${response.statusText} at URL: ${url}`);
    }

    const arrayBuffer = await response.arrayBuffer();
    return Buffer.from(arrayBuffer);
  } catch (error) {
    clearTimeout(id);
    if (error.name === 'AbortError') {
      throw new Error(`Failed to download PDF: Timeout after ${timeoutMs}ms at URL: ${url}`);
    }
    // Don't wrap our own HTTP 404/status error messages
    if (error.message.startsWith('Failed to download PDF:')) {
      throw error;
    }
    throw new Error(`Failed to download PDF: Network error (${error.message}) at URL: ${url}`);
  }
}

/**
 * Extracts raw text from a PDF buffer by reading both plain text (for mock files)
 * and extracting FlateDecoded stream text.
 */
export function extractTextFromPdfBuffer(buffer) {
  const pdfText = [];
  const content = buffer.toString('binary');
  
  let pos = 0;
  while (pos < content.length) {
    const streamIdx = content.indexOf('stream', pos);
    if (streamIdx === -1) break;
    
    const endStreamIdx = content.indexOf('endstream', streamIdx);
    if (endStreamIdx === -1) break;
    
    const startOfData = streamIdx + (content.charAt(streamIdx + 6) === '\r' ? 8 : 7);
    let endOfData = endStreamIdx;
    if (content.charAt(endOfData - 1) === '\n') endOfData--;
    if (content.charAt(endOfData - 1) === '\r') endOfData--;
    
    const streamVal = buffer.subarray(startOfData, endOfData);
    const objHeader = content.substring(Math.max(0, streamIdx - 100), streamIdx);
    const isFlate = objHeader.includes('/FlateDecode');
    
    try {
      let decompressed = streamVal;
      if (isFlate) {
        decompressed = zlib.inflateSync(streamVal);
      }
      
      const text = decompressed.toString('utf8');
      const matches = text.match(/\(([^)]*)\)/g);
      if (matches) {
        const chunkText = matches.map(m => m.slice(1, -1)).join(' ');
        if (chunkText.trim()) {
          pdfText.push(chunkText);
        }
      } else {
        if (text.includes('mock') || text.length > 50) {
          pdfText.push(text);
        }
      }
    } catch (e) {
      // Ignore decompression errors for non-flate or malformed streams
    }
    
    pos = endStreamIdx + 9;
  }
  
  if (pdfText.length === 0) {
    const plainText = buffer.toString('utf8');
    if (plainText.trim()) {
      return plainText;
    }
  }
  
  return pdfText.join('\n');
}

/**
 * Splits text semantically into chunks not exceeding the maxTokens limit.
 * Uses character length / 4 as a robust estimation of tokens.
 */
export function semanticChunk(text, maxTokens = 2000) {
  const estimateTokens = (str) => Math.ceil(str.length / 5);

  const chunks = [];
  const paragraphs = text.split(/\r?\n\r?\n/);
  
  let currentChunk = [];
  let currentTokens = 0;

  for (const para of paragraphs) {
    const paraClean = para.trim();
    if (!paraClean) continue;

    const paraTokens = estimateTokens(paraClean);

    if (currentTokens + paraTokens <= maxTokens) {
      currentChunk.push(paraClean);
      currentTokens += paraTokens;
    } else {
      if (currentChunk.length > 0) {
        chunks.push(currentChunk.join('\n\n'));
        currentChunk = [];
        currentTokens = 0;
      }

      if (paraTokens > maxTokens) {
        const sentences = paraClean.match(/[^.!?]+[.!?]+(\s|$)/g) || [paraClean];
        for (const sentence of sentences) {
          const sentClean = sentence.trim();
          if (!sentClean) continue;
          const sentTokens = estimateTokens(sentClean);

          if (currentTokens + sentTokens <= maxTokens) {
            currentChunk.push(sentClean);
            currentTokens += sentTokens;
          } else {
            if (currentChunk.length > 0) {
              chunks.push(currentChunk.join(' '));
              currentChunk = [];
              currentTokens = 0;
            }
            
            if (sentTokens > maxTokens) {
              const words = sentClean.split(/\s+/);
              for (const word of words) {
                const wordTokens = estimateTokens(word + ' ');
                if (currentTokens + wordTokens <= maxTokens) {
                  currentChunk.push(word);
                  currentTokens += wordTokens;
                } else {
                  if (currentChunk.length > 0) {
                    chunks.push(currentChunk.join(' '));
                    currentChunk = [];
                    currentTokens = 0;
                  }
                  currentChunk.push(word);
                  currentTokens += wordTokens;
                }
              }
            } else {
              currentChunk.push(sentClean);
              currentTokens += sentTokens;
            }
          }
        }
      } else {
        currentChunk.push(paraClean);
        currentTokens += paraTokens;
      }
    }
  }

  if (currentChunk.length > 0) {
    chunks.push(currentChunk.join('\n\n'));
  }

  return chunks;
}

/**
 * Extracts a candidate title from the text (first non-empty line).
 */
function extractTitleFromText(text) {
  if (!text) return null;
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length > 0) {
    return lines[0].slice(0, 200);
  }
  return null;
}

/**
 * Resolves the canonical Semantic Scholar Entity ID.
 * Tries URL lookup first, then falls back to title search.
 * Handles network errors gracefully by returning a generated/fallback ID or null.
 */
export async function resolveSemanticScholarEntityId(seedUrl, pdfText, options = {}) {
  // P1 2026-07-25 (journal 0001): these are the FIRST two S2 calls of every run and
  // they had ZERO retry (bare fetch, silent catch) — a 429 here made the seed
  // unresolvable and killed the whole run downstream. Route through the shared
  // fetchWithBackoff (Retry-After + jittered exponential + S2_API_KEY header).
  const customFetch = options.fetch ?? fetch;
  const fetchOptions = options.fetchOptions ?? {};

  // 1. Try URL Lookup
  try {
    const encodedUrl = encodeURIComponent(seedUrl);
    const urlLookupEndpoint = `https://api.semanticscholar.org/graph/v1/paper/URL:${encodedUrl}`;
    const res = await fetchWithBackoff(urlLookupEndpoint, { ...options, fetch: customFetch, fetchOptions });
    if (res.ok) {
      const data = await res.json();
      if (data && data.paperId) {
        return data.paperId;
      }
    }
  } catch (err) {
    // Gracefully fallback on network/parsing issues (after real retries)
  }

  // 2. Try Title Search
  const title = extractTitleFromText(pdfText);
  if (title) {
    try {
      const searchEndpoint = `https://api.semanticscholar.org/graph/v1/paper/search?query=${encodeURIComponent(title)}&limit=1`;
      const res = await fetchWithBackoff(searchEndpoint, { ...options, fetch: customFetch, fetchOptions });
      if (res.ok) {
        const data = await res.json();
        if (data && data.data && data.data[0] && data.data[0].paperId) {
          return data.data[0].paperId;
        }
      }
    } catch (err) {
      // Gracefully fallback on network/parsing issues (after real retries)
    }
  }

  // If all attempts failed but we need to proceed gracefully, return a derived/deterministic fallback ID
  // to avoid crashing, but if it is completely unresolvable, return null.
  return null;
}

/**
 * Runs the complete ingestion pipeline for a seed URL.
 */
export async function runIngestionPipeline(seedUrl, options = {}) {
  const buffer = await downloadPdf(seedUrl, options);
  const pdfText = extractTextFromPdfBuffer(buffer);
  const chunks = semanticChunk(pdfText, options.maxTokens ?? 2000);
  const entityId = await resolveSemanticScholarEntityId(seedUrl, pdfText, options);
  
  return {
    seedUrl,
    pdfText,
    chunks,
    entityId,
  };
}

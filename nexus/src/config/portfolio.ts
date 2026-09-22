/**
 * The portfolio.
 *
 * Positions live here rather than in a database because this is a personal OS:
 * one user, one file, editable in ten seconds. Prices, day changes and history
 * are fetched live - only the units and what you paid are local, because no
 * public API knows those.
 *
 * Override the whole thing with a NEXUS_PORTFOLIO env var containing JSON of
 * the same shape.
 */

export interface Position {
  symbol: string;
  name: string;
  sector: string;
  units: number;
  /** Average price paid per unit, in the instrument's own currency. */
  costBasis: number;
}

export const DEFAULT_PORTFOLIO: Position[] = [
  { symbol: 'NVDA', name: 'NVIDIA', sector: 'Semiconductors', units: 12, costBasis: 118.4 },
  { symbol: 'AAPL', name: 'Apple', sector: 'Consumer tech', units: 20, costBasis: 189.2 },
  { symbol: 'MSFT', name: 'Microsoft', sector: 'Software', units: 8, costBasis: 372.5 },
  { symbol: 'GOOGL', name: 'Alphabet', sector: 'Software', units: 15, costBasis: 141.8 },
  { symbol: 'ASML', name: 'ASML', sector: 'Semiconductors', units: 3, costBasis: 690.0 },
  { symbol: 'TSLA', name: 'Tesla', sector: 'Automotive', units: 10, costBasis: 242.7 },
];

export function readPortfolio(): Position[] {
  const raw = process.env.NEXUS_PORTFOLIO;
  if (!raw) return DEFAULT_PORTFOLIO;
  try {
    const parsed = JSON.parse(raw) as Position[];
    if (Array.isArray(parsed) && parsed.length > 0) return parsed;
  } catch {
    // A malformed override should not take the module down with it.
  }
  return DEFAULT_PORTFOLIO;
}

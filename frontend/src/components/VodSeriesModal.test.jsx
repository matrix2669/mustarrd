import { describe, expect, it } from 'vitest'

import { extractSeriesTmdbId } from './VodSeriesModal'


describe('VOD series TMDB metadata normalization', () => {
  it('extracts a numeric TMDB id from detailed series metadata', () => {
    expect(extractSeriesTmdbId({ info: { tmdb_id: 1438 } })).toBe('1438')
  })

  it('extracts a TMDB id from a provider URL', () => {
    expect(
      extractSeriesTmdbId({ info: { tmdb: 'https://www.themoviedb.org/tv/1438' } })
    ).toBe('1438')
  })

  it('falls back to series-list metadata', () => {
    expect(extractSeriesTmdbId({}, { tmdb_id: 1438 })).toBe('1438')
  })

  it('returns null for unusable metadata', () => {
    expect(extractSeriesTmdbId({ info: { tmdb_id: 'unknown' } })).toBeNull()
  })
})

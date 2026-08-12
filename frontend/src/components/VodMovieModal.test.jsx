import { describe, expect, it } from 'vitest'

import { extractReleaseDate, extractTmdbId } from './VodMovieModal'


describe('VOD movie metadata normalization', () => {
  it('normalizes a numeric provider year to a string', () => {
    expect(extractReleaseDate({ info: { year: 2026 } })).toBe('2026')
  })

  it('prefers a release date over a fallback year', () => {
    expect(
      extractReleaseDate({ info: { releasedate: '2026-08-01', year: 2026 } })
    ).toBe('2026-08-01')
  })

  it('extracts a numeric TMDB id from provider metadata', () => {
    expect(extractTmdbId({ info: { tmdb_id: 123456 } })).toBe('123456')
  })

  it('extracts the id from a TMDB URL', () => {
    expect(
      extractTmdbId({ info: { tmdb: 'https://www.themoviedb.org/movie/693134' } })
    ).toBe('693134')
  })

  it('returns null when no usable TMDB id is available', () => {
    expect(extractTmdbId({ info: { tmdb_id: 'not-a-tmdb-id' } })).toBeNull()
  })
})

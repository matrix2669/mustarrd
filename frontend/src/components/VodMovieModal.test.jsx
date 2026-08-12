import { describe, expect, it } from 'vitest'

import { extractReleaseDate, extractTmdbId, resolveMovieMetadata } from './VodMovieModal'


describe('VOD movie metadata normalization', () => {
  it('normalizes a numeric provider year to a string', () => {
    expect(extractReleaseDate({ info: { year: 2026 } })).toBe('2026')
  })

  it('prefers a release date over a fallback year', () => {
    expect(
      extractReleaseDate({ info: { releasedate: '2026-08-01', year: 2026 } })
    ).toBe('2026-08-01')
  })

  it('falls through an empty release date to provider year', () => {
    expect(extractReleaseDate({ info: { releasedate: '', year: 2026 } })).toBe('2026')
  })

  it('extracts a numeric TMDB id from provider metadata', () => {
    expect(extractTmdbId({ info: { tmdb_id: 123456 } })).toBe('123456')
  })

  it('extracts the id from a TMDB URL', () => {
    expect(
      extractTmdbId({ info: { tmdb: 'https://www.themoviedb.org/movie/693134' } })
    ).toBe('693134')
  })

  it('falls through an empty TMDB id to an alternate provider field', () => {
    expect(extractTmdbId({ info: { tmdb_id: '', tmdb: 693134 } })).toBe('693134')
  })

  it('falls back to movie-list metadata when detailed VOD info omits TMDB and year', () => {
    expect(
      resolveMovieMetadata(
        { info: { plot: 'Detailed response without IDs' } },
        { tmdb_id: '1049471', year: 2026 }
      )
    ).toEqual({
      releaseDate: '2026',
      tmdbId: '1049471',
    })
  })

  it('prefers detailed metadata when it is available', () => {
    expect(
      resolveMovieMetadata(
        { info: { tmdb_id: '693134', releasedate: '2024-02-27' } },
        { tmdb_id: '1', year: 2024 }
      )
    ).toEqual({
      releaseDate: '2024-02-27',
      tmdbId: '693134',
    })
  })

  it('returns null when no usable TMDB id is available', () => {
    expect(extractTmdbId({ info: { tmdb_id: 'not-a-tmdb-id' } })).toBeNull()
  })
})
import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type {
  CohortResponse,
  DeviceDataResponse,
  IndividualDataResponse,
  ClinicalTimelineResponse,
  VisitScatterResponse,
  CohortFilters
} from './types'

export function useCohortFilter(filters: CohortFilters, additionalFilters?: Record<string, string>) {
  return useQuery({
    queryKey: ['cohort', filters, additionalFilters],
    queryFn: async () => {
      const params: any = { ...filters }

      // Add additional filters as JSON string
      if (additionalFilters && Object.keys(additionalFilters).length > 0) {
        params.filters = JSON.stringify(additionalFilters)
      }

      const { data } = await api.get<CohortResponse>('/cohorts/filter', { params })
      return data
    },
    enabled: Object.keys(filters).some(k => filters[k as keyof CohortFilters] != null) ||
             (additionalFilters && Object.keys(additionalFilters).length > 0),
  })
}

export function useDeviceData(
  cohortIds: string[],
  minDay?: number,
  maxDay?: number
) {
  return useQuery({
    queryKey: ['device-data', cohortIds, minDay, maxDay],
    queryFn: async () => {
      const params: any = { cohort_ids: cohortIds.join(',') }
      if (minDay !== undefined) params.min_day = minDay
      if (maxDay !== undefined) params.max_day = maxDay

      const { data } = await api.get<DeviceDataResponse>('/device-data/aggregated', { params })
      return data
    },
    enabled: cohortIds.length > 0,
  })
}

export function useIndividualData(
  usubjid: string | null,
  metrics: string,
  minDay?: number,
  maxDay?: number
) {
  return useQuery({
    queryKey: ['individual-data', usubjid, metrics, minDay, maxDay],
    queryFn: async () => {
      const params: any = { usubjid, metrics }
      if (minDay !== undefined) params.min_day = minDay
      if (maxDay !== undefined) params.max_day = maxDay

      const { data } = await api.get<IndividualDataResponse>('/device-data/individual', { params })
      return data
    },
    enabled: !!usubjid,
  })
}

export function useParticipantsWithData(cohortIds: string[]) {
  return useQuery({
    queryKey: ['participants-with-data', cohortIds],
    queryFn: async () => {
      const { data } = await api.get<{ participants: string[] }>('/device-data/participants-with-data', {
        params: { cohort_ids: cohortIds.join(',') },
      })
      return data
    },
    enabled: cohortIds.length > 0,
  })
}

export function useClinicalTimeline(cohortIds: string[]) {
  return useQuery({
    queryKey: ['clinical-timeline', cohortIds],
    queryFn: async () => {
      const { data } = await api.get<ClinicalTimelineResponse>('/clinical-data/visit-timeline', {
        params: { cohort_ids: cohortIds.join(',') },
      })
      return data
    },
    enabled: cohortIds.length > 0,
  })
}

export function useVisitScatter(cohortIds: string[]) {
  return useQuery({
    queryKey: ['visit-scatter', cohortIds],
    queryFn: async () => {
      const { data } = await api.get<VisitScatterResponse>('/clinical-data/visit-scatter', {
        params: { cohort_ids: cohortIds.join(',') },
      })
      return data
    },
    enabled: cohortIds.length > 0,
  })
}

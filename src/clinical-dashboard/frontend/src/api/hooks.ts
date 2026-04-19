import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { CohortResponse, DeviceDataResponse, ClinicalTimelineResponse, CohortFilters } from './types'

export function useCohortFilter(filters: CohortFilters) {
  return useQuery({
    queryKey: ['cohort', filters],
    queryFn: async () => {
      const { data } = await api.get<CohortResponse>('/cohorts/filter', { params: filters })
      return data
    },
    enabled: Object.keys(filters).some(k => filters[k as keyof CohortFilters] != null),
  })
}

export function useDeviceData(cohortIds: string[]) {
  return useQuery({
    queryKey: ['device-data', cohortIds],
    queryFn: async () => {
      const { data } = await api.get<DeviceDataResponse>('/device-data/aggregated', {
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

export interface CohortFilters {
  sex?: string
  min_age?: number
  max_age?: number
  disease?: string
  medication?: string
}

export interface Participant {
  usubjid: string
  sex: string
  age_at_enrollment: number
}

export interface CohortResponse {
  cohort_id: string
  filters: CohortFilters
  total_participants: number
  participants: Participant[]
}

export interface DeviceMetricPoint {
  study_day: number
  mean: number
  std: number
  count: number
}

export interface DeviceDataResponse {
  cohort_size: number
  metrics: {
    steps?: DeviceMetricPoint[]
    sleep?: DeviceMetricPoint[]
    hrv?: DeviceMetricPoint[]
    walking_bouts?: DeviceMetricPoint[]
    nonwalking_bouts?: DeviceMetricPoint[]
  }
}

export interface VisitPoint {
  visit_num: number
  visit_name: string
  sbp_mean: number
  sbp_std: number
  dbp_mean: number
  dbp_std: number
  hr_mean: number
  hr_std: number
  count: number
}

export interface ClinicalTimelineResponse {
  cohort_size: number
  visits: VisitPoint[]
}

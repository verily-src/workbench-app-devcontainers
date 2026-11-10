package org.broadinstitute.variantinterpretation.controller;

import org.broadinstitute.variantinterpretation.api.ConditionApi;
import org.broadinstitute.variantinterpretation.datasource.ConditionLookupService;
import org.broadinstitute.variantinterpretation.datasource.QueryUsageMeter;
import org.broadinstitute.variantinterpretation.model.ConditionCandidates;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

/**
 * Condition concept lookup for the phenotype search box's dropdown.
 */
@RestController
public class ConditionController implements ConditionApi {

  private final ConditionLookupService conditionLookup;
  private final QueryUsageMeter usage;

  public ConditionController(ConditionLookupService conditionLookup, QueryUsageMeter usage) {
    this.conditionLookup = conditionLookup;
    this.usage = usage;
  }

  @Override
  public ResponseEntity<ConditionCandidates> conditionCandidates(String condition) {
    usage.beginConditionLookup(condition == null ? "" : condition.trim());
    try {
      return ResponseEntity.ok(conditionLookup.candidates(condition));
    } finally {
      usage.endSearch();
    }
  }
}

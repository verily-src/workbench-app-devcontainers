package org.broadinstitute.variantinterpretation.controller;

import org.broadinstitute.variantinterpretation.api.ProfileApi;
import org.broadinstitute.variantinterpretation.model.UserProfile;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ProfileController implements ProfileApi {

  private final String userEmail;

  public ProfileController(@Value("${WORKBENCH_USER_EMAIL:}") String userEmail) {
    this.userEmail = userEmail;
  }

  @Override
  public ResponseEntity<UserProfile> profile() {
    return ResponseEntity.ok(new UserProfile().userEmail(userEmail));
  }
}

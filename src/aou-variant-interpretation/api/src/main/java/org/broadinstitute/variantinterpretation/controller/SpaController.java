package org.broadinstitute.variantinterpretation.controller;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * Forwards client-side routes (e.g. /results) to index.html so React Router can take over,
 * instead of Spring's static resource handler 404ing on a direct load or page refresh.
 */
@Controller
public class SpaController {

  @GetMapping({"/results"})
  public String forwardToIndex() {
    return "forward:/index.html";
  }
}

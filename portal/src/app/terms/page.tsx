import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Use - Atlas Property Feasibility API",
  description:
    "Terms of Use for the Atlas Property Feasibility API, including the preliminary-information disclaimer, acceptable use, and limitation of liability.",
};

const UPDATED = "July 21, 2026";

export default function TermsPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <p className="font-mono text-xs uppercase tracking-widest text-teal-700">
        Legal
      </p>
      <h1 className="mt-3 text-3xl font-bold tracking-tight">Terms of Use</h1>
      <p className="mt-2 text-sm text-neutral-500">Last updated: {UPDATED}</p>

      <div className="mt-8 space-y-6 leading-relaxed text-neutral-700">
        <p>
          These Terms of Use govern access to and use of the Atlas Property
          Feasibility API and related documentation and developer portal (the
          &quot;Service&quot;). By requesting an API key, calling any endpoint,
          or otherwise using the Service, you agree to these terms. If you do
          not agree, do not use the Service.
        </p>

        <section>
          <h2 className="text-xl font-semibold tracking-tight">
            1. What the Service is, and is not
          </h2>
          <p className="mt-2">
            The Service returns preliminary, informational zoning and GIS
            analysis for real property, beginning with California accessory
            dwelling unit (ADU), junior ADU (JADU), and SB 9 projects. Results
            are automated estimates derived from public data sources and
            published rules. They are not legal, architectural, surveying,
            engineering, title, environmental, lending, or permitting advice,
            and they are not a permit, entitlement, approval, or guarantee of
            any outcome.
          </p>
          <p className="mt-2">
            The Service never states that a project is approved, legal to build,
            or guaranteed. Every result is expressed as a feasibility status
            (likely_feasible, likely_constrained, needs_professional_review, or
            insufficient_data) and includes citations, assumptions, limitations,
            and a disclaimer. You must independently verify all results with the
            applicable jurisdiction and qualified licensed professionals before
            making decisions or spending money.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold tracking-tight">
            2. No warranty
          </h2>
          <p className="mt-2">
            The Service is provided &quot;as is&quot; and &quot;as
            available,&quot; without warranties of any kind, express or implied,
            including merchantability, fitness for a particular purpose,
            accuracy, completeness, currency, or non-infringement. Public data
            sources may be incomplete, out of date, or in error, and rules
            change. We do not warrant that results are accurate or that the
            Service will be uninterrupted or error free.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold tracking-tight">
            3. Limitation of liability
          </h2>
          <p className="mt-2">
            To the maximum extent permitted by law, in no event will the Service
            or its operators be liable for any indirect, incidental, special,
            consequential, or punitive damages, or for any loss of profits,
            revenue, data, or goodwill, arising out of or related to your use of
            or inability to use the Service, even if advised of the possibility
            of such damages. Aggregate liability for any claim will not exceed
            the amount you paid for the Service in the three months preceding the
            claim.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold tracking-tight">
            4. Acceptable use
          </h2>
          <p className="mt-2">
            You will not misrepresent Service results as definitive legal or
            professional determinations; present results to consumers or third
            parties without the accompanying disclaimer, citations, and
            limitations; attempt to exceed, evade, or reverse-engineer rate
            limits or metering; or use the Service in any unlawful manner or to
            build a substantially similar competing dataset by systematic
            extraction. You are responsible for your API credentials and for all
            use under them.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold tracking-tight">
            5. Data sources and attribution
          </h2>
          <p className="mt-2">
            Results incorporate data from public sources including municipal
            code publishers, city and county GIS services (for example Los
            Angeles City ZIMAS and the Los Angeles County Assessor), FEMA, CAL
            FIRE, and the California Department of Housing and Community
            Development. Those sources are owned by their respective publishers
            and remain subject to their own terms. The Service preserves source
            citations so you can verify each value against its origin.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold tracking-tight">
            6. Billing and plans
          </h2>
          <p className="mt-2">
            Access is offered through RapidAPI plans. A billable unit is one
            completed address-level feasibility analysis (one address and one
            project type resolving to a terminal feasibility status). Errors and
            unsupported-coverage responses are not billed, and identical inputs
            from the same consumer within a 24-hour window are treated as a
            cache hit and not billed again. Plan quotas and prices are described
            on the pricing page and in the RapidAPI listing.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold tracking-tight">
            7. Changes and termination
          </h2>
          <p className="mt-2">
            We may modify the Service or these terms at any time; material
            changes will be reflected by the &quot;last updated&quot; date
            above. We may suspend or terminate access for violation of these
            terms or to protect the Service. Sections 2 through 5 survive
            termination.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold tracking-tight">8. Contact</h2>
          <p className="mt-2">
            Questions about these terms can be sent through the support channel
            listed on the RapidAPI listing.
          </p>
        </section>

        <p className="rounded-md border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-500">
          This document is a starting template provided for launch and is not
          legal advice. Have it reviewed by qualified counsel before relying on
          it in production, and align it with your RapidAPI provider agreement.
        </p>
      </div>
    </main>
  );
}

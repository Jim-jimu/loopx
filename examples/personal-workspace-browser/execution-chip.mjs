import { resolve } from "node:path";

import { outputDir } from "./fixture.mjs";
import { openWorkspacePage } from "./scenario-context.mjs";

// The credential-resolved binding the Chat service projects once an operator
// supplied a model credential: the steward model follows that credential while
// the managed host still lacks a chat transport.
const bindingWithOperatorCredential = {
  schema_version: "manager_channel_binding_v0",
  executor_endpoint: "codex",
  executor_endpoint_source: "operator_credential",
  executor_transport_reason: "dsh_chat_transport_unsupported",
  model: "deepseek-flash",
  model_source: "operator_credential_default",
  credential_env_var: "DEEPSEEK_API_KEY",
  operator_credential_configured: true,
};

export const executionChipScenario = {
  id: "execution-chip",
  async run({ browser, collectCoverage, url }) {
    const context = await openWorkspacePage(browser, url, {
      apiOptions: { managerChannelBinding: bindingWithOperatorCredential },
      collectCoverage,
    });
    const { close, coverageEntries, page } = context;
    try {
      const chip = page.locator(".personal-execution-chip");
      await chip.waitFor({ state: "visible" });
      const chipText = (await chip.innerText()).replace(/\s+/g, " ").trim();
      for (const expected of ["codex", "deepseek-flash", "operator 凭据"]) {
        if (!chipText.includes(expected)) {
          throw new Error(`Execution chip omitted ${expected}: ${chipText}`);
        }
      }
      const note = page.locator(".personal-execution-note");
      await note.waitFor({ state: "visible" });
      const noteText = (await note.innerText()).replace(/\s+/g, " ").trim();
      if (!noteText.includes("托管执行器尚无 Chat 通道") || !noteText.includes("codex")) {
        throw new Error(`Transport note did not name the pending managed host: ${noteText}`);
      }
      if (await page.getByText("deepseek-flash", { exact: false }).count() === 0) {
        throw new Error("Resolved steward model never reached the rendered header");
      }
      const headerBox = await page.locator(".personal-channel-header").boundingBox();
      const chipBox = await chip.boundingBox();
      if (!headerBox || !chipBox) throw new Error("Execution chip has no layout box");
      if (chipBox.y < headerBox.y || chipBox.y + chipBox.height > headerBox.y + headerBox.height) {
        throw new Error("Execution chip escaped the channel header row");
      }
      if (chipBox.height > 26) {
        throw new Error(`Execution chip is not a compact hairline row: ${chipBox.height}px tall`);
      }
      await page.screenshot({
        animations: "disabled",
        fullPage: false,
        path: resolve(outputDir, "execution-chip-manager-header.png"),
      });
      await close();
    } catch (error) {
      await page.screenshot({
        animations: "disabled",
        fullPage: false,
        path: resolve(outputDir, "execution-chip-failed.png"),
      });
      throw error;
    }

    // A control plane that projects no binding keeps the previous header.
    const withoutBinding = await openWorkspacePage(browser, url, { collectCoverage });
    try {
      if (await withoutBinding.page.locator(".personal-execution-chip").count() !== 0) {
        throw new Error("Execution chip rendered without a projected channel binding");
      }
    } finally {
      coverageEntries.push(...await withoutBinding.close());
    }
    return {
      coverageEntries,
      note: "execution chip and transport note render from the projected binding, and stay absent without one",
    };
  },
};

import { useState } from "react";
import { Badge, Button, EmptyState, SectionCard, SuggestInput, toast } from "../../../components/system";
import { useAxiomMutation, useAxiomQuery } from "../../../hooks/useAxiomQuery";
import { useWorkspaceRoster } from "../../../hooks/useWorkspaceRoster";
import { fetchAdminRoles, updateAdminRole } from "../../../lib/api";

/*
 * RolesTab (G3) — assign workspace users a governance role. Admin-only (the
 * whole Control Center surface is admin-gated upstream). Reads the explicit
 * role roster from GET /api/admin/roles and assigns via PUT /api/admin/roles;
 * the email picker autofills from the real account roster.
 */

const ROLE_TONE = { admin: "bad", steward: "good", writer: "info", reader: "muted" };
const ROLE_HINT = {
  reader: "Read-only access to governed metadata.",
  writer: "Can edit metadata (comments, tags, glossary).",
  steward: "Can approve requests, classifications, and glossary terms.",
  admin: "Full administration — including role assignment.",
};

function compact(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const parsed = Date.parse(text);
  return Number.isNaN(parsed) ? text : new Date(parsed).toLocaleDateString();
}

export function RolesTab() {
  const { query } = useAxiomQuery({
    key: ["admin", "roles"],
    fetch: (signal) => fetchAdminRoles({ signal }),
    staleTime: 30_000,
  });
  const data = query.data || {};
  const roles = Array.isArray(data.roles) ? data.roles : [];
  const assignable = Array.isArray(data.assignableRoles) && data.assignableRoles.length
    ? data.assignableRoles
    : ["reader", "writer", "steward", "admin"];

  const roster = useWorkspaceRoster({ enabled: true });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("steward");

  const assign = useAxiomMutation({
    mutate: (payload) => updateAdminRole(payload.email, payload.role),
    invalidates: [["admin", "roles"]],
  });

  const submit = async (event) => {
    event.preventDefault();
    const normalized = email.trim().toLowerCase();
    if (!normalized || assign.submitting) return;
    try {
      await assign.mutate({ email: normalized, role });
      toast(`${normalized} set to ${role}.`, { tone: "success" });
      setEmail("");
    } catch {
      /* assign.errorMessage renders inline below the form. */
    }
  };

  return (
    <div className="ax-admin-panel" id="ax-admin-panel-roles" role="tabpanel">
      <SectionCard
        title="Assign a role"
        subtitle="Grant a workspace user a governance role. Assigning an existing user updates their role."
      >
        <form aria-label="Assign a governance role" className="ax-admin-roles-form" onSubmit={submit}>
          <label className="ax-admin-roles-field">
            <span>User email</span>
            <SuggestInput
              disabled={assign.submitting}
              onChange={(event) => setEmail(event.target.value)}
              options={roster.emails}
              placeholder="user@your-company.ai"
              required
              type="email"
              value={email}
            />
          </label>
          <label className="ax-admin-roles-field">
            <span>Role</span>
            <select
              className="ax-admin-roles-select"
              disabled={assign.submitting}
              onChange={(event) => setRole(event.target.value)}
              value={role}
            >
              {assignable.map((option) => (
                <option key={option} value={option}>
                  {option.charAt(0).toUpperCase() + option.slice(1)}
                </option>
              ))}
            </select>
          </label>
          <Button disabled={!email.trim()} loading={assign.submitting} size="sm" type="submit" variant="primary">
            Assign role
          </Button>
        </form>
        <p className="ax-admin-roles-hint">{ROLE_HINT[role]}</p>
        {assign.errorMessage ? (
          <p className="ax-admin-form-error" role="alert">
            {assign.errorMessage}
          </p>
        ) : null}
      </SectionCard>

      <SectionCard
        title="Assigned roles"
        subtitle="Users with an explicit governance role (bootstrap admins included)."
        status={query.isPending && !query.data ? "loading" : undefined}
      >
        {roles.length ? (
          <div className="ax-admin-roles-scroll">
            <table className="ax-admin-roles-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Assigned by</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {roles.map((entry) => (
                  <tr key={entry.email}>
                    <td>{entry.email}</td>
                    <td><Badge tone={ROLE_TONE[entry.role] || "neutral"}>{entry.role}</Badge></td>
                    <td>{entry.updatedBy || "—"}</td>
                    <td>{compact(entry.updatedAt) || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No explicit role assignments"
            body="Every user defaults to reader. Assign a role above to grant write, steward, or admin access."
          />
        )}
      </SectionCard>
    </div>
  );
}

export default RolesTab;

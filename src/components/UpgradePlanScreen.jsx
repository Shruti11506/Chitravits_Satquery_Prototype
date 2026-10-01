import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Check,
  Crown,
  Gauge,
  HelpCircle,
  Image as ImageIcon,
  Info,
  LifeBuoy,
  MessageSquare,
  Minus,
  User,
  Users,
  Wrench,
  Zap,
} from 'lucide-react';
import {
  FEATURE_COMPARISON,
  PRICING_PLANS,
  formatPrice,
  monthlyPriceFor,
} from '../data/pricingPlans';
import './ProfileDashboard.css';
import './UpgradePlan.css';

const PLAN_ICONS = { user: User, zap: Zap, users: Users };
const FEATURE_ICONS = {
  queries: BarChart3,
  imagery: ImageIcon,
  speed: Gauge,
  tools: Wrench,
  team: Users,
  support: LifeBuoy,
};

// There is no billing backend yet, so these actions say so honestly instead of
// pretending a payment or a support request went through.
const NOT_AVAILABLE = {
  upgrade: 'Online payments aren’t available yet. Plan upgrades will open here once billing is connected.',
  support: 'Support contact isn’t set up yet.',
  docs: 'Documentation isn’t published yet.',
  features: 'The full feature list isn’t published yet.',
};

function HeaderArt() {
  return (
    <svg className="up-head-art" viewBox="0 0 440 170" aria-hidden="true">
      <defs>
        <radialGradient id="up-planet" cx="38%" cy="32%" r="70%">
          <stop offset="0%" stopColor="#60a5fa" />
          <stop offset="45%" stopColor="#1d4ed8" />
          <stop offset="100%" stopColor="#020617" />
        </radialGradient>
        <radialGradient id="up-glow" cx="50%" cy="50%" r="50%">
          <stop offset="60%" stopColor="#3b82f6" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="up-layer" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#1e3a8a" stopOpacity="0.15" />
        </linearGradient>
      </defs>

      {/* Layered data stack */}
      {[0, 1, 2].map((i) => (
        <path
          key={i}
          d={`M70 ${78 + i * 18} L120 ${54 + i * 18} L170 ${78 + i * 18} L120 ${102 + i * 18} Z`}
          fill="url(#up-layer)"
          stroke="#60a5fa"
          strokeOpacity={0.55 - i * 0.12}
          strokeWidth="1"
        />
      ))}
      <path d="M104 78 L120 70 L136 78 L120 86 Z" fill="none" stroke="#93c5fd" strokeOpacity="0.7" />

      {/* Planet + orbit */}
      <circle cx="300" cy="96" r="92" fill="url(#up-glow)" />
      <circle cx="300" cy="96" r="64" fill="url(#up-planet)" />
      <path
        d="M262 74 q14 -10 30 -4 q8 10 -4 18 q-12 4 -20 -2 z M300 108 q16 -6 26 4 q-2 14 -18 14 q-10 -6 -8 -18 z M318 60 q10 0 14 8 q-6 6 -14 2 z"
        fill="#93c5fd"
        fillOpacity="0.22"
      />
      <ellipse
        cx="300"
        cy="100"
        rx="118"
        ry="30"
        fill="none"
        stroke="#60a5fa"
        strokeOpacity="0.35"
        transform="rotate(-14 300 100)"
      />

      {/* Satellite */}
      <g transform="translate(392 30) rotate(35)">
        <rect x="-7" y="-7" width="14" height="14" rx="2" fill="#1e40af" stroke="#93c5fd" strokeOpacity="0.8" />
        <rect x="-36" y="-5" width="24" height="10" rx="1.5" fill="#1d4ed8" stroke="#60a5fa" strokeOpacity="0.8" />
        <rect x="12" y="-5" width="24" height="10" rx="1.5" fill="#1d4ed8" stroke="#60a5fa" strokeOpacity="0.8" />
      </g>
      <circle cx="96" cy="30" r="1.4" fill="#93c5fd" fillOpacity="0.7" />
      <circle cx="214" cy="20" r="1" fill="#93c5fd" fillOpacity="0.6" />
      <circle cx="420" cy="132" r="1.2" fill="#93c5fd" fillOpacity="0.6" />
    </svg>
  );
}

function ComparisonValue({ value, accent }) {
  if (value === true) return <Check size={16} className={`up-cmp-check up-accent-${accent}`} aria-label="Included" />;
  if (value === false) return <Minus size={14} className="up-cmp-dash" aria-label="Not included" />;
  return <span className={`up-cmp-text up-accent-${accent}`}>{value}</span>;
}

export function UpgradePlanScreen({ currentPlan }) {
  const [billing, setBilling] = useState('monthly');
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const showToast = (message) => {
    clearTimeout(toastTimer.current);
    setToast(message);
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  };

  // currentPlan comes from GET /profile; until it loads, no card claims to be current.
  const currentIndex = PRICING_PLANS.findIndex((p) => p.id === currentPlan);

  return (
    <div className="pf-page up-page">
      {toast && (
        <div className="model-toast animate-fadeIn" role="status">
          <Info size={16} className="text-blue-400" />
          <span>{toast}</span>
        </div>
      )}

      {/* Header */}
      <header className="up-head">
        <div className="up-head-text">
          <h1 className="up-title">Upgrade Plan</h1>
          <p className="up-subtitle">Get more from SATQuery with a plan that fits your needs.</p>
          <p className="up-support-text">
            Unlock higher usage limits, advanced analysis tools, faster processing, and priority support.
          </p>
        </div>
        <HeaderArt />
      </header>

      {/* Billing toggle */}
      <div className="up-toggle-row">
        <div className="up-toggle" role="radiogroup" aria-label="Billing period">
          <span className={`up-toggle-thumb${billing === 'yearly' ? ' is-yearly' : ''}`} aria-hidden="true" />
          <button
            type="button"
            role="radio"
            aria-checked={billing === 'monthly'}
            className={`up-toggle-btn${billing === 'monthly' ? ' is-active' : ''}`}
            onClick={() => setBilling('monthly')}
          >
            Monthly
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={billing === 'yearly'}
            className={`up-toggle-btn${billing === 'yearly' ? ' is-active' : ''}`}
            onClick={() => setBilling('yearly')}
          >
            Yearly
            <span className="up-save-badge">Save 20%</span>
          </button>
        </div>
      </div>

      {/* Pricing cards */}
      <section className="up-plans" aria-label="Plans">
        {PRICING_PLANS.map((plan, index) => {
          const Icon = PLAN_ICONS[plan.icon];
          const price = monthlyPriceFor(plan, billing);
          const isCurrent = index === currentIndex;
          const isIncluded = currentIndex > -1 && index < currentIndex;
          return (
            <article key={plan.id} className={`up-plan up-plan-${plan.accent}${isCurrent ? ' is-current' : ''}`}>
              {plan.badge && (
                <span className="up-plan-badge">
                  <Crown size={12} />
                  {plan.badge}
                </span>
              )}
              <div className="up-plan-head">
                <span className="up-plan-icon">
                  <Icon size={20} />
                </span>
                <div className="up-plan-heading">
                  <h2 className="up-plan-name">{plan.name}</h2>
                  <p className="up-plan-desc">{plan.description}</p>
                </div>
              </div>

              <div className="up-plan-price">
                <span className="up-price-value">{formatPrice(price)}</span>
                <span className="up-price-unit">/ month</span>
              </div>
              <p className="up-price-note">
                {billing === 'yearly' && plan.monthlyPrice > 0
                  ? `Billed ${formatPrice(price * 12)} yearly`
                  : ' '}
              </p>

              {isCurrent || isIncluded ? (
                <button type="button" className="up-plan-btn up-plan-btn-current" disabled>
                  {isCurrent ? 'Current Plan' : 'Included in your plan'}
                </button>
              ) : (
                <button
                  type="button"
                  className="up-plan-btn up-plan-btn-cta"
                  onClick={() => showToast(NOT_AVAILABLE.upgrade)}
                >
                  {plan.monthlyPrice === 0 ? `Switch to ${plan.name}` : `Upgrade to ${plan.name}`}
                </button>
              )}

              <ul className="up-plan-features">
                {plan.features.map((feature) => (
                  <li key={feature}>
                    <span className="up-feature-check">
                      <Check size={12} strokeWidth={3} />
                    </span>
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </section>

      {/* Feature comparison */}
      <section className="pf-card up-compare" aria-labelledby="up-compare-title">
        <div className="up-compare-head">
          <div>
            <h2 id="up-compare-title" className="up-section-title">Feature Comparison</h2>
            <p className="up-section-sub">See what's included in each plan.</p>
          </div>
          <button type="button" className="up-link" onClick={() => showToast(NOT_AVAILABLE.features)}>
            View full feature list <ArrowRight size={14} />
          </button>
        </div>

        <div className="up-table-scroll">
          <div className="up-table" role="table" aria-label="Feature comparison">
            <div className="up-row up-row-head" role="row">
              <span role="columnheader">Feature</span>
              <span role="columnheader" className="up-col">Free</span>
              <span role="columnheader" className="up-col up-col-pro up-accent-blue">Pro</span>
              <span role="columnheader" className="up-col up-accent-purple">Team</span>
            </div>
            {FEATURE_COMPARISON.map((row) => {
              const Icon = FEATURE_ICONS[row.icon];
              return (
                <div key={row.feature} className="up-row" role="row">
                  <span role="cell" className="up-feature-name">
                    <Icon size={15} className="up-feature-icon" />
                    {row.feature}
                  </span>
                  <span role="cell" className="up-col">
                    <ComparisonValue value={row.free} accent="neutral" />
                  </span>
                  <span role="cell" className="up-col up-col-pro">
                    <ComparisonValue value={row.pro} accent="blue" />
                  </span>
                  <span role="cell" className="up-col">
                    <ComparisonValue value={row.team} accent="purple" />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Support */}
      <section className="pf-card up-help">
        <span className="up-help-icon">
          <HelpCircle size={20} />
        </span>
        <div className="up-help-text">
          <h2 className="up-help-title">Need help choosing a plan?</h2>
          <p className="up-help-sub">Contact our support team or check out our documentation.</p>
        </div>
        <div className="up-help-actions">
          <button type="button" className="up-ghost-btn" onClick={() => showToast(NOT_AVAILABLE.support)}>
            <MessageSquare size={15} /> Contact Support
          </button>
          <button type="button" className="up-ghost-btn" onClick={() => showToast(NOT_AVAILABLE.docs)}>
            <BookOpen size={15} /> View Documentation
          </button>
        </div>
      </section>
    </div>
  );
}

// Upgrade Plan page (UpgradePlanScreen.jsx) configuration. Static product copy,
// kept in one place so it can later come from a billing backend. The user's
// current plan is NOT here -- it comes from GET /profile (`profile.plan`).

export const YEARLY_DISCOUNT = 0.2;

export const PRICING_PLANS = [
  {
    id: 'free',
    name: 'Free',
    description: 'Get started with essential features.',
    monthlyPrice: 0,
    accent: 'neutral',
    icon: 'user',
    features: [
      'Limited analysis queries',
      'Basic satellite imagery access',
      'Standard processing speed',
      'Community support',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    description: 'For researchers and professionals.',
    monthlyPrice: 29,
    accent: 'blue',
    icon: 'zap',
    badge: 'Most Popular',
    features: [
      '5× more analysis queries',
      'Access to premium satellite imagery',
      'Faster processing speed',
      'Advanced analysis tools',
      'Priority support',
    ],
  },
  {
    id: 'team',
    name: 'Team',
    description: 'For organizations and teams.',
    monthlyPrice: 99,
    accent: 'purple',
    icon: 'users',
    features: [
      'Unlimited analysis queries',
      'Full satellite imagery library',
      'Fastest processing speed',
      'Advanced analysis tools',
      'Team collaboration',
      'Dedicated support',
    ],
  },
];

// `true` renders a check, `false` a dash, a string renders as-is.
export const FEATURE_COMPARISON = [
  { feature: 'Analysis queries per month', icon: 'queries', free: '50', pro: '250', team: 'Unlimited' },
  { feature: 'Satellite imagery access', icon: 'imagery', free: 'Basic', pro: 'Premium', team: 'Full library' },
  { feature: 'Processing speed', icon: 'speed', free: 'Standard', pro: 'Fast', team: 'Fastest' },
  { feature: 'Advanced analysis tools', icon: 'tools', free: false, pro: true, team: true },
  { feature: 'Team collaboration', icon: 'team', free: false, pro: false, team: true },
  { feature: 'Priority support', icon: 'support', free: false, pro: true, team: true },
];

/** Price per month for the chosen billing period (yearly = 20% off). */
export function monthlyPriceFor(plan, billing) {
  return billing === 'yearly' ? plan.monthlyPrice * (1 - YEARLY_DISCOUNT) : plan.monthlyPrice;
}

export function formatPrice(value) {
  return Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2)}`;
}

import { ref, computed } from 'vue'

const lang = ref('EN')

function toggleLang() {
  lang.value = lang.value === 'EN' ? 'UA' : 'EN'
}

const STRINGS = {
  EN: {
    // App header
    appTitle: 'Transport Interchange Decision Support System',
    appSubtitle: 'Multi-Criteria Decision Analysis (MCDA) · Weighted Sum Model (WSM)',

    // Tabs
    tabEvaluation: 'DSS Evaluation',
    tabGallery: 'Blueprint Gallery',
    tabMethodology: 'Methodology',

    // Sidebar
    sidebarVersion: 'TDSS v4',
    taskContext: 'Task Context',
    taskContextDesc: 'Select the interchange type category to compare alternatives.',
    criteriaWeights: 'Criteria Weights',
    criteriaWeightsDesc: 'Adjust slider values. Weights are auto-normalised to sum to 1.0.',
    projectParameters: 'Project Parameters',
    projectParamsDesc: 'Define site-specific constraints and traffic characteristics.',
    normWeightsLabel: 'Normalised weights (sum = 1.0)',
    rawTotalLabel: 'Raw slider total',
    dataFooter: 'Data: FHWA (2023) · HCM 7th Ed. · PIARC Road Safety Manual (2022).',

    // Criteria labels
    constructionCost: 'Construction Cost',
    landArea: 'Land Area',
    throughput: 'Throughput (vph)',
    safetyIndex: 'Safety Index',

    // Criteria directions
    minimize: 'Minimize',
    maximize: 'Maximize',

    // Param labels
    designSpeed: 'Design Speed (km/h)',
    aadt: 'AADT',
    peakFactor: 'Peak Hour Factor (%)',
    numLanes: 'Lanes / Direction',
    budget: 'Budget (M USD)',
    landLimit: 'Available Land (ha)',
    terrainType: 'Terrain Type',
    envSensitivity: 'Environmental Sensitivity',

    // Terrain options
    terrainFlat: 'Flat',
    terrainRolling: 'Rolling',
    terrainMountainous: 'Mountainous',

    // Env options
    envLow: 'Low',
    envMedium: 'Medium',
    envHigh: 'High',
    envCritical: 'Critical',

    // DSS Evaluation
    updating: 'Updating…',
    context: 'Context',
    recommended: 'Recommended',
    wsmScore: 'WSM Score',
    rankOf: 'rank #1 of',
    alternatives: 'alternatives in',
    designSpeedLabel: 'Design Speed',
    aadtLabel: 'AADT',
    budgetLimit: 'Budget Limit',
    landLimitLabel: 'Land Limit',
    peakHourFactor: 'Peak Hour Factor',
    lanesPerDir: 'Lanes / Direction',
    terrain: 'Terrain',
    envSens: 'Env. Sensitivity',
    paramAdjustments: 'Parameter Adjustments Applied',
    wsmRanking: 'WSM Score Ranking',
    tapToExplore: 'Tap any card to explore its detailed engineering profile, metrics, and real-world map.',
    details: '→  Details',
    close: '✕  Close',
    detailedAnalysis: 'Detailed Analysis',
    engineeringDesc: 'Engineering Description',
    advantages: 'Advantages',
    limitations: 'Limitations',
    realWorldExample: 'Real-world example',
    coordinates: 'Coordinates',
    satellite: 'Satellite imagery (Esri)',
    criterionValues: 'Criterion Values',
    normScores: 'Normalised Scores and Weighted Contributions',
    normDesc: 'Min-Max normalisation maps each raw value to [0, 1]. Minimize criteria are inverted so 1.0 denotes the best performer. Cell format: normalised x̄ᵢⱼ → weighted contribution wⱼ · x̄ᵢⱼ.',
    rank: 'Rank',
    alternative: 'Alternative',
    cost: 'Cost (M USD)',
    landAreaCol: 'Land Area (ha)',
    throughputCol: 'Throughput (vph)',
    safetyCol: 'Safety Index',
    norm: 'norm',
    feasibility: 'Feasibility',
    feasible: '✅ Feasible',
    overLimit: '⚠ Over limit',

    // Blueprint Gallery
    blueprints: 'Interchange Schematic Blueprints',
    projectParamsSummary: 'Project Parameters',
    designSpeedShort: 'Design Speed',
    peakFactorShort: 'Peak Factor',
    lanesShort: 'Lanes',
    budgetShort: 'Budget',
    landShort: 'Land',
    terrainShort: 'Terrain',
    envShort: 'Env',
    dir: '/dir',
    allAlternatives: 'All Alternatives',
    feasibleCheck: '✓ Feasible',
    exceedsLimits: '✗ Exceeds limits',
    criterionLabel: 'Criterion',
    directionCol: 'Direction',
    rawValue: 'Raw Value',
    normalised: 'Normalised',
    weight: 'Weight',
    contribution: 'Contribution',

    // Methodology
    wsmTitle: 'Weighted Sum Model (WSM)',
    wsmDesc: 'The composite priority score for alternative i is computed as the weighted sum of normalised criterion values:',
    symbol: 'Symbol',
    definition: 'Definition',
    defSi: 'Composite WSM score for alternative i, Sᵢ ∈ [0, 1]',
    defN: 'Number of evaluation criteria',
    defWj: 'Normalised weight for criterion j, with Σwⱼ = 1',
    defXij: 'Min-Max normalised value of criterion j for alternative i',
    minMaxTitle: 'Min-Max Normalisation',
    minMaxDesc: 'Raw criterion values are mapped to the unit interval [0, 1] according to the direction of preference.',
    maxDir: 'Maximize — higher raw value is preferred (e.g. throughput, safety):',
    minDir: 'Minimize — lower raw value is preferred (e.g. cost, land area):',
    edgeCase: 'Edge case: when maxⱼ = minⱼ (all alternatives equal), the normalised score is set to 0.5.',
    criteriaDataTitle: 'Criteria and Data Sources',
    source: 'Source',
    referencesTitle: 'References',
    activeWeightProfile: 'Active Weight Profile',
    currentRanking: 'Current Ranking',
    ordinals: ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th'],

    // Chart strings
    chartRadarTitle: 'Normalised Criterion Profile — Top',
    chartBarTitle: 'WSM Score Ranking',
    chartBarXAxis: 'WSM Composite Score',
    chartStackTitle: 'Weighted Contribution Breakdown',
    chartStackXAxis: 'Summed Weighted Contribution',
    chartContribution: 'Contribution',

    // Terrain display names (for param cards)
    terrainDisplay: { Flat: 'Flat', Rolling: 'Rolling', Mountainous: 'Mountainous' },
    envDisplay: { Low: 'Low', Medium: 'Medium', High: 'High', Critical: 'Critical' },
  },

  UA: {
    // App header
    appTitle: `Система підтримки прийняття рішень щодо транспортних розв\u2019язок`,
    appSubtitle: 'Багатокритеріальний аналіз рішень (MCDA) · Метод зваженої суми (WSM)',

    // Tabs
    tabEvaluation: 'Оцінювання DSS',
    tabGallery: 'Галерея схем',
    tabMethodology: 'Методологія',

    // Sidebar
    sidebarVersion: 'TDSS v4',
    taskContext: 'Контекст задачі',
    taskContextDesc: `Оберіть категорію транспортних розв\u2019язок для порівняння альтернатив.`,
    criteriaWeights: 'Ваги критеріїв',
    criteriaWeightsDesc: 'Змінюйте значення повзунків. Ваги автоматично нормалізуються до суми 1,0.',
    projectParameters: 'Параметри проєкту',
    projectParamsDesc: `Вкажіть обмеження та транспортні характеристики об\u2019єкту.`,
    normWeightsLabel: 'Нормалізовані ваги (сума = 1,0)',
    rawTotalLabel: 'Сума повзунків',
    dataFooter: 'Дані: FHWA (2023) · HCM 7-е вид. · Посібник з дорожньої безпеки PIARC (2022).',

    // Criteria labels
    constructionCost: 'Вартість будівництва',
    landArea: 'Площа ділянки',
    throughput: 'Пропускна здатність (авт/год)',
    safetyIndex: 'Індекс безпеки',

    // Criteria directions
    minimize: 'Мінімізувати',
    maximize: 'Максимізувати',

    // Param labels
    designSpeed: 'Розрахункова швидкість (км/год)',
    aadt: 'AADT (середньорічна добова інтенсивність)',
    peakFactor: 'Частка пікової години (%)',
    numLanes: 'Смуг на напрямок',
    budget: 'Бюджет (млн USD)',
    landLimit: 'Доступна площа (га)',
    terrainType: 'Тип рельєфу',
    envSensitivity: 'Екологічна чутливість',

    // Terrain options
    terrainFlat: 'Рівнина',
    terrainRolling: 'Пересічена місцевість',
    terrainMountainous: 'Гірська місцевість',

    // Env options
    envLow: 'Низька',
    envMedium: 'Середня',
    envHigh: 'Висока',
    envCritical: 'Критична',

    // DSS Evaluation
    updating: 'Оновлення…',
    context: 'Контекст',
    recommended: 'Рекомендовано',
    wsmScore: 'Оцінка WSM',
    rankOf: 'місце 1 з',
    alternatives: 'альтернатив у',
    designSpeedLabel: 'Розр. швидкість',
    aadtLabel: 'AADT',
    budgetLimit: 'Ліміт бюджету',
    landLimitLabel: 'Ліміт площі',
    peakHourFactor: 'Частка піку',
    lanesPerDir: 'Смуг/напрямок',
    terrain: 'Рельєф',
    envSens: 'Екол. чутливість',
    paramAdjustments: 'Застосовані корективи за параметрами проєкту',
    wsmRanking: 'Рейтинг оцінок WSM',
    tapToExplore: 'Натисніть на картку, щоб переглянути інженерний профіль, метрики та карту реального об\u2019єкту.',
    details: '→  Деталі',
    close: '✕  Закрити',
    detailedAnalysis: 'Детальний аналіз',
    engineeringDesc: 'Інженерний опис',
    advantages: 'Переваги',
    limitations: 'Недоліки',
    realWorldExample: 'Реальний приклад',
    coordinates: 'Координати',
    satellite: 'Супутникові знімки (Esri)',
    criterionValues: 'Значення критеріїв',
    normScores: 'Нормалізовані оцінки та зважені внески',
    normDesc: 'Мін-макс нормалізація відображає сирі значення на відрізок [0, 1]. Критерії мінімізації інвертуються — оцінка 1,0 відповідає найкращому показнику. Формат клітинки: нормалізоване x̄ᵢⱼ → зважений внесок wⱼ · x̄ᵢⱼ.',
    rank: 'Ранг',
    alternative: 'Альтернатива',
    cost: 'Вартість (млн USD)',
    landAreaCol: 'Площа (га)',
    throughputCol: 'Пропускна здатн. (авт/год)',
    safetyCol: 'Індекс безпеки',
    norm: 'норм.',
    feasibility: 'Прийнятність',
    feasible: '✅ Прийнятна',
    overLimit: '⚠ Перевищення',

    // Blueprint Gallery
    blueprints: `Схематичні креслення розв\u2019язок`,
    projectParamsSummary: 'Параметри проєкту',
    designSpeedShort: 'Розр. швидкість',
    peakFactorShort: 'Частка піку',
    lanesShort: 'Смуги',
    budgetShort: 'Бюджет',
    landShort: 'Площа',
    terrainShort: 'Рельєф',
    envShort: 'Екол.',
    dir: '/нап.',
    allAlternatives: 'Усі альтернативи',
    feasibleCheck: '✓ Прийнятна',
    exceedsLimits: '✗ Перевищує ліміти',
    criterionLabel: 'Критерій',
    directionCol: 'Напрямок',
    rawValue: 'Сире значення',
    normalised: 'Нормалізоване',
    weight: 'Вага',
    contribution: 'Внесок',

    // Methodology
    wsmTitle: 'Метод зваженої суми (WSM)',
    wsmDesc: 'Комплексна пріоритетна оцінка альтернативи i — це зважена сума нормалізованих значень за всіма критеріями:',
    symbol: 'Символ',
    definition: 'Визначення',
    defSi: 'Комплексна оцінка WSM для альтернативи i, Sᵢ ∈ [0, 1]',
    defN: 'Кількість критеріїв оцінювання',
    defWj: 'Нормалізована вага критерію j, де Σwⱼ = 1',
    defXij: 'Мін-макс нормалізоване значення критерію j для альтернативи i',
    minMaxTitle: 'Мін-макс нормалізація',
    minMaxDesc: 'Сирі значення критеріїв відображаються на одиничний відрізок [0, 1] відповідно до напрямку переваги.',
    maxDir: 'Максимізація — вище значення є кращим (напр. пропускна здатність, безпека):',
    minDir: 'Мінімізація — нижче значення є кращим (напр. вартість, площа):',
    edgeCase: 'Граничний випадок: якщо maxⱼ = minⱼ (усі альтернативи рівні), нормалізована оцінка дорівнює 0,5.',
    criteriaDataTitle: 'Критерії та джерела даних',
    source: 'Джерело',
    referencesTitle: 'Список літератури',
    activeWeightProfile: 'Поточний профіль ваг',
    currentRanking: 'Поточний рейтинг',
    ordinals: ['1-е', '2-е', '3-є', '4-е', '5-е', '6-е', '7-е', '8-е'],

    // Chart strings
    chartRadarTitle: 'Нормалізований профіль критеріїв — Топ',
    chartBarTitle: 'Рейтинг оцінок WSM',
    chartBarXAxis: 'Комплексна оцінка WSM',
    chartStackTitle: 'Розбивка зважених внесків',
    chartStackXAxis: 'Зважений внесок (сума)',
    chartContribution: 'Внесок',

    // Terrain/Env display names for param cards
    terrainDisplay: { Flat: 'Рівнина', Rolling: 'Пересічена', Mountainous: 'Гірська' },
    envDisplay: { Low: 'Низька', Medium: 'Середня', High: 'Висока', Critical: 'Критична' },
  },
}

const t = computed(() => STRINGS[lang.value])

export function useLocale() {
  return { lang, toggleLang, t }
}
